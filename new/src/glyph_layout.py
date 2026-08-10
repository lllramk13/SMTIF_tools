"""Glyph-index constraints shared by the codetable, fonts and text pipeline.

These are facts about the game, not policy, so everything that has to agree on
where a glyph index may live reads them from here.

Two experimental code-layout plans used to live alongside this (a static-text
alias plan and a dynamic low-code relocation plan).  Both were superseded by
``unified_normal_text_plan`` plus ``f14_context_aliases`` and have been moved to
``archive/src/``; only the constants and helpers below survived them.
"""
from src.text_codec import encode_text


# F14 (the static font) holds 4 bit planes x 346 cells = 0x567 glyphs, so
# 0x0566 is the highest index it can draw.  Anything a static screen renders
# must land at or below this or it comes out blank -- and the out-of-range read
# paints stray coloured tiles next to it.
ORIGINAL_MAX_GLYPH_INDEX = 0x0566

# Sections whose records are drawn through F14 rather than the dynamic font.
STATIC_TEXT_SECTION = "text_17"
STATIC_TEXT_SECTIONS = (STATIC_TEXT_SECTION, "text_88")

# Every Chinese glyph is full width, so the static advance is constant.
STATIC_WIDTH = 0x0B

# The static width table at 0x800F2910 is one byte per glyph and is physically
# only 0x567 entries long -- the *menu* width table starts right after it at
# 0x800F2E80 -- so it cannot grow beyond F14's own capacity.
STATIC_WIDTH_TABLE_ENTRIES = 0x0567

# Low codes the original UI addresses directly by index, so a translated glyph
# must never take them over.
#
# 0x068..0x108 used to be here too: 161 cells holding the original kana, kept
# so keyboard-entered Japanese names would still draw.  They are the single
# biggest block of low codes in the game and the reason F14 was permanently
# 2 cells over capacity, forcing the whole F14-context-alias mechanism -- which
# in turn only repaints F14, so any alias-encoded record that also appears in a
# dynamic-font screen came out as kana (撕咬 -> キヂ).  The project decided
# Japanese name entry is not needed, so the kana block is released: every
# character that needed an alias now gets a real low code and renders correctly
# in both fonts.
#
# What stays reserved is what the executable hardcodes as glyph indices:
# punctuation, the fullwidth digits and Latin letters behind ＮＯ　ＤＡＴＡ,
# ＦＩＬＥ n and the map header's floor Ｆ (0x039).  Freeing those is what
# turned 学校1Ｆ into 学校1＋.
#
# 0x02A..0x033 (fullwidth ０-９) left this set on 2026-07-30.  The map header
# builds its floor number as `digit + 0x2A`, so those ten cells used to be held
# back for the original glyphs -- ten cells F14 could not spend on Chinese,
# which is exactly what put it 10 over capacity once demon and race names joined
# the static set.
#
# The codetable now *pins* our own ０-９ onto those same ten cells instead (see
# tools/rearrange_codetable.DIGIT_PINS).  The header's arithmetic is unchanged
# and still lands on a fullwidth zero, just drawn from our font, so no code
# patch is needed -- and because those characters already needed low cells,
# pinning them releases ten cells outright.
#
# The seven punctuation cells 0x004-0x007, 0x00D, 0x010 and 0x015 left this set
# on 2026-07-30, for exactly the same reason the digits did.  0x015 holds the
# map header's 「－」 (貪欲界１Ｆ－Ａ) and the game draws it by index, so once the
# alias allocator reached down that far the header read 贪欲界１Ｆ率Ａ.
#
# Every one of the seven is a character our own text already uses, so pinning
# our copy onto the original's cell renders the same glyph with no code patch --
# and, because those characters needed a low cell anyway, it hands seven cells
# back to F14.  See tools/rearrange_codetable.PUNCTUATION_PINS.
#
# Ａ Ｂ Ｆ (0x034, 0x035, 0x039) followed on the same day and for the same
# reason.  The save screen draws Ａ and Ｂ by index and the map header's floor
# suffix is Ｆ, so they could never be aliased -- yet all three are ordinary
# characters our text already uses hundreds of times, so pinning our copies onto
# their cells renders them correctly *and* returns the cells to F14.
#
# What is left is the Latin block Ｃ-Ｚ.  Even though most of it is not indexed
# directly by executable code, player names keep these original codes in RAM.
# Mixed Chinese/Latin names take the F14 renderer, so every one of these cells
# must remain Latin there.  The unified plan still reserves the cells to move
# their displaced Chinese characters to high F13 codes; F14 context aliases now
# use the separate released pool in mixed_name_layout.py.
DYNAMIC_SPECIAL_LOW_INDICES = frozenset(
    index for index in range(0x034, 0x04E)
    if index not in (0x034, 0x035, 0x039)
)


def glyph_indices(character_codes, text):
    """Glyph indices ``text`` needs, ignoring control codes and the terminator."""
    encoded = encode_text(character_codes, text)
    indices = set()

    for position in range(0, len(encoded), 2):
        code = encoded[position:position + 2]
        if len(code) != 2 or code == b"\xFF\xFF":
            break

        # All IF control codes use FF as their second byte.  They are not font
        # glyphs and must not be counted against the glyph budget.
        if code[1] != 0xFF:
            indices.add(int.from_bytes(code, "little"))

    return indices


def build_static_width_overrides(width=STATIC_WIDTH):
    """Use a full-width advance for every glyph the width table can hold."""
    if not 0 <= width <= 0x0F:
        raise ValueError(f"Static glyph width is out of range: {width:#x}")
    return {
        glyph_index: width
        for glyph_index in range(STATIC_WIDTH_TABLE_ENTRIES)
    }
