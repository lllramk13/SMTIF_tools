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

# Low codes the original name-entry / one-byte UI paths use directly.  Normal
# translated dialogue must not depend on their low-code meaning; F14 context
# aliases deliberately reuse these cells for menu-only records.
DYNAMIC_SPECIAL_LOW_INDICES = frozenset((
    0x004,
    0x005,
    0x006,
    0x007,
    0x00D,
    0x010,
    0x015,
    *range(0x02A, 0x04E),
    *range(0x068, 0x109),
))


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
