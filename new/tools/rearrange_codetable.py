#!/usr/bin/env python3
"""Regenerate data/codetable.json's index layout for the current translation.

Constraints encoded here (discovered the hard way; see memory notes):

1. The table must be contiguous (load_codetable rejects gaps), indices 0..N-1.
2. Index 0 must be the full-width space: the original game leaves glyph 0
   empty and the name-entry UI inserts it for a blank; font_builder also
   forces glyph 0 transparent.
3. Hardcoded UI codes must keep their patched meaning.  The status screen's
   six stat abbreviations are drawn from a fixed table of glyph codes, so
   力知魔体速运 are pinned to the indices used by executable_patch.py.
4. Characters used by static/F14-rendered text must land below 0x567 (F14's
   capacity).  That includes text_17/text_88, static SLPM slots, the F0098
   name tables, and every string that can appear in the party panel (preset
   partner names and demon names), because the party panel renders names
   straight from F14 since the 0x8006C27C -> 0x800475FC patch.
5. Everything else fills the remaining non-reserved indices; overflow goes to
   the reserved name-entry range and is relocated at build time by
   unified_normal_text_plan (destination pool is large enough as long as the
   overflow stays a couple hundred characters).

Run from new/:  python tools/rearrange_codetable.py
Writes data/codetable.json in place (backup at data/codetable.json.bak).
"""
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from src.glyph_layout import (
    DYNAMIC_SPECIAL_LOW_INDICES,
    ORIGINAL_MAX_GLYPH_INDEX,
    STATIC_TEXT_SECTIONS,
    glyph_indices,
)
from src.text_codec import load_character_codes
from src.text_records import choose_text, load_text_data
from src.slpm_text import load_slpm_text_records, translated_slpm_texts
from src.f0098_text import load_f0098_text_records, translated_f0098_texts
from src.overlay_text import (
    load_overlay_text_records,
    translated_overlay_texts,
)
from src.font_builder import load_codetable

CODETABLE = NEW_DIR / 'data' / 'codetable.json'
BASELINE = NEW_DIR / 'data' / 'codetable.json.prerearrange.bak'

SPACE = '　'
# Hardcoded stat-abbreviation codes (SLPM table at 0xE5C20 stores these glyph
# indices directly).  executable_patch.py changes the last entry from the
# original 運=0x131 to the simplified Chinese 运=0x180.
PINS = {0x53B: '力', 0x3CD: '知', 0x4D2: '魔', 0x3A8: '体', 0x39A: '速', 0x180: '运'}
# The Chinese name-entry keyboard does not return a code of its own: pressing a
# cell yields the *original* hardwired code behind it (0x068..0x107, see
# src/name_entry.SOURCE_CODE_ROWS).  So every one of its 160 characters has to
# sit on exactly the cell its key returns, or build_name_entry_plan rejects the
# table with "not aligned with the grid's hardwired return codes".
#
# Without these pins a rearrange silently scatters those 160 characters and the
# whole keyboard breaks -- which is easy to trigger, because the translators
# rerun this script whenever they introduce a new character.
def _name_entry_pins():
    import json

    from src.name_entry import SOURCE_CODE_ROWS

    rows = json.loads(
        (NEW_DIR / 'data' / 'name_entry_characters.json').read_text(
            encoding='utf-8'
        )
    )['rows']
    pins = {}
    for row, codes in zip(rows, SOURCE_CODE_ROWS):
        for character, code in zip(row, codes):
            pins[code] = character
    if len(pins) != 160:
        raise SystemExit(
            f'name-entry keyboard should pin 160 cells, got {len(pins)}'
        )
    return pins


PINS.update(_name_entry_pins())

# The map header builds its floor number as `digit + 0x2A`, so cells
# 0x02A..0x033 must hold ０-９ in ascending order.  Pinning our own fullwidth
# digits there keeps that arithmetic valid with no code patch at all, and since
# these characters already needed low cells it costs nothing -- while releasing
# the ten cells the reserved set used to hold for the original glyphs.  That is
# exactly the 10-cell shortfall demon and race names created.
DIGIT_PINS = {
    0x02A + offset: character
    for offset, character in enumerate('０１２３４５６７８９')
}
PINS.update(DIGIT_PINS)
# Preset partner names shown in the party panel.
PARTY_PRESET_NAMES = ('由美', '查理', '明')
# Hardcoded single glyphs patched into the executable at build time
# (executable_patch.py resolves their codes from the codetable): 智 replaces
# the intelligence stat's 知, 等 is the name-plural suffix (達 -> 等).  Both
# render via F14, so they must stay below 0x567.
EXTRA_STATIC_UI_CHARS = ('智', '等')
# The two upgrade-screen strings that shift_jis_ui.py rewrites into fixed slots
# and redirects to F14.  They are hardcoded UI, so every character must have a
# real low code; the builder asserts this and fails the build otherwise.
DIRECT_UI_F14_TEXTS = ('这样可以吗？', '剩余点数')
# Item names (weapons/armor/guns/bullets...) shown on equip and shop screens,
# which render via the F14 static font: every character must stay < 0x567 or
# it blanks out (e.g. armor rows showing only 头/肩/轮).
ITEM_NAME_BLOCK_PREFIX = 'F0094-00001008'
# Negotiation / action menus (「要做什么呢?」「什么技艺?」…).  These option lists
# render through the F14 static font too, so an option whose code landed above
# 0x567 draws as a blank -- and the out-of-range read paints stray coloured
# tiles next to it.  Same failure mode as the equipment item names above.
MENU_OPTION_BLOCK_PREFIXES = (
    'F0076-00002C7C',
    'F0084-00000800',
    'F0084-0000E000',
)
# Skill names (the demon detail screen) render through F14 too.  This table was
# never in the static set, which is why e.g. Pixie's ジオンガ -> 雷霆 lost 霆
# (0x855) and painted a stray tile next to it.
SKILL_NAME_BLOCK_PREFIXES = (
    'F0094-00002630',
)
# Demon names and race names, both drawn by F14 in the analysis/summon lists.
# Neither was ever in the static set, which is the same omission that lost
# 霆 from 雷霆 and blanked the armour rows: a character that only appears here
# keeps a high code, F14 cannot reach it, and the glyph comes out empty --
# 凶鸟 rendered as 鸟 and 花子 as 子.  The out-of-range reads are also what
# makes those lists crawl.
DEMON_NAME_BLOCK_PREFIXES = (
    'F0094-0000003C',
    'F0094-000039F8',
)


def demon_name_texts(text_data):
    return [
        choose_text(record)
        for records in text_data.values()
        for record in records
        if record.get('id', '').startswith(DEMON_NAME_BLOCK_PREFIXES)
        and choose_text(record)
    ]

# Blocks that are drawn by F14 and used to be handled with F14 context aliases
# instead of real low codes.  Releasing the 161 kana cells freed enough room to
# give them ordinary indices, which is what makes them render correctly in the
# dynamic font too -- an alias only repaints F14, so 撕咬 came out as キヂ in
# the F13 skill list.
# The green help panel (F0094-00002070 item/magic, F0094-00002D98 skill
# descriptions) is confirmed F14-only, so it can keep using context aliases --
# an alias is only wrong when the same record also appears in a dynamic-font
# screen.  Everything below does appear in both and therefore needs a real
# low code.
F14_CONTEXT_BLOCK_PREFIXES = (
    'F0094-00000000',
    'F0094-00002630',
    'F0076-00002C7C',
    'F0084-00000800',
    'F0084-0000E000',
)
# Confirmed F14-only: the green help panel.  Its characters are still static,
# but they are the ones allowed to spill onto reserved cells and pick up an
# F14 context alias when the low range runs out -- an alias is only wrong for
# a record that also shows up in a dynamic-font screen, and these do not.
F14_ONLY_BLOCK_PREFIXES = (
    'F0094-00002070',
    'F0094-00002D98',
)


def f14_only_texts(text_data):
    return [
        record['translation']
        for record in text_data.get('texts', ())
        if record.get('id', '').startswith(F14_ONLY_BLOCK_PREFIXES)
        and isinstance(record.get('translation'), str)
        and record['translation']
    ]
# SLPM ranges that the same mechanism covered: action results, MARKER help,
# the map-header area names and the equipment/resistance descriptions.
F14_CONTEXT_SLPM_RANGES = (
    (0xE6A26, 0xE6D58),
    (0xEF298, 0xEF33C),
    (0xE4768, 0xE48A8),
    (0xE7BF0, 0xE813A),
)


def f14_context_texts(text_data, slpm_records, f0098_records):
    """Every translation that is rendered through F14 via a context block."""
    texts = []
    for record in text_data.get('texts', ()):
        if not record.get('id', '').startswith(F14_CONTEXT_BLOCK_PREFIXES):
            continue
        translation = record.get('translation')
        if isinstance(translation, str) and translation:
            texts.append(translation)
    for record in slpm_records:
        translation = record['translation']
        if not translation:
            continue
        if any(lo <= record['offset'] < hi for lo, hi in F14_CONTEXT_SLPM_RANGES):
            texts.append(translation)
    texts.extend(translated_f0098_texts(f0098_records, renderer='static'))
    return texts


# Shop/service menus live in the F0049 overlay and render through F14 too, so
# their option characters must stay below 0x567 or they come out blank (「贩卖」
# lost 贩 exactly this way).  Only the short, punctuation-free rows are options;
# the shop's chatter goes through the dynamic font.
#
# F0092's short rows are excluded on purpose: they are internal scenario-flag
# labels (「去往傲慢区」「傲慢区开门」…), and pulling their 24 extra characters in
# would overflow F14's remaining slots.
OVERLAY_MENU_FILES = ('F0049',)
OVERLAY_MENU_MAX_CHARS = 6
_OVERLAY_SENTENCE_MARKS = '。！？，、'
_OVERLAY_STRIP = re.compile('\\{[^}]*\\}|[\\n\\u3000]')


def overlay_menu_option_texts():
    """Short F0049 overlay rows, i.e. the shop/service menu options."""
    options = []
    for file_name, rows in load_overlay_text_records().items():
        if file_name not in OVERLAY_MENU_FILES:
            continue
        for row in rows:
            translation = row.get('translation') or ''
            if not translation or translation == (row.get('source') or ''):
                continue
            core = _OVERLAY_STRIP.sub('', translation)
            if len(core) > OVERLAY_MENU_MAX_CHARS:
                continue
            if any(mark in core for mark in _OVERLAY_SENTENCE_MARKS):
                continue
            options.append(translation)
    return options


def skill_name_texts(text_data):
    """Translations of the F0094 skill-name table (rendered via F14)."""
    names = []
    for record in text_data.get('texts', ()):
        if not record.get('id', '').startswith(SKILL_NAME_BLOCK_PREFIXES):
            continue
        translation = record.get('translation')
        if isinstance(translation, str) and translation:
            names.append(translation)
    return names


def menu_option_texts(text_data):
    """Translations of the negotiation/action option blocks (F14-rendered)."""
    options = []
    for record in text_data.get('texts', ()):
        record_id = record.get('id', '')
        if not record_id.startswith(MENU_OPTION_BLOCK_PREFIXES):
            continue
        translation = record.get('translation')
        if isinstance(translation, str) and translation:
            options.append(translation)
    return options


def item_name_texts(text_data):
    """Translations of the F0094 item-name table (rendered via F14)."""
    names = []
    for record in text_data.get('texts', ()):
        if not record.get('id', '').startswith(ITEM_NAME_BLOCK_PREFIX):
            continue
        translation = record.get('translation')
        if isinstance(translation, str) and translation:
            names.append(translation)
    return names

KATAKANA_NAME = re.compile(r'^[ァ-ヶー・]+$')


def party_name_texts(text_data):
    """Strings that can appear as party-member names (rendered via F14)."""
    names = list(PARTY_PRESET_NAMES)
    for record in text_data.get('texts', ()):
        source = record.get('source')
        translation = record.get('translation')
        if (
            record.get('id', '').startswith('F0040')
            and isinstance(source, str)
            and KATAKANA_NAME.match(source.strip() or 'x')
            and isinstance(translation, str)
            and translation
        ):
            names.append(translation)
    return names


def main():
    base = BASELINE if BASELINE.is_file() else CODETABLE
    codetable = load_codetable(base)
    character_codes = load_character_codes(base)
    char2idx = {
        ch: int.from_bytes(code, 'little')
        for ch, code in character_codes.items()
    }
    all_chars = set(char2idx)
    count = len(all_chars)

    text_data = load_text_data(NEW_DIR / 'data' / 'text.json')
    slpm = load_slpm_text_records()
    f98 = load_f0098_text_records()

    def chars_of(text):
        return {
            codetable[i]
            for i in glyph_indices(character_codes, text)
            if i in codetable
        }

    used, static = set(), set()
    for section, records in text_data.items():
        for record in records:
            chars = chars_of(choose_text(record))
            used |= chars
            if section in STATIC_TEXT_SECTIONS:
                static |= chars
    for text in translated_slpm_texts(slpm, 'dynamic'):
        used |= chars_of(text)
    # F0098 action-name strings marked static are encoded through the same
    # context aliases as the F14 action-result box.  They still need global
    # codes as alias-plan inputs, but must not consume globally unique low
    # cells merely because that one insertion context is F14.
    for text in translated_f0098_texts(f98, 'static'):
        used |= chars_of(text)
    # Overlay text is injected too, so its characters are used.  Without this a
    # character that appears only there looks unused and can land on a reserved
    # name-entry code, where original_ui_glyphs paints a kana over it.
    for text in translated_overlay_texts():
        used |= chars_of(text)
    for text in (
        translated_slpm_texts(slpm, 'static')
        + translated_f0098_texts(f98, 'dynamic')
        + tuple(party_name_texts(text_data))
        + tuple(item_name_texts(text_data))
        + tuple(overlay_menu_option_texts())
        + tuple(skill_name_texts(text_data))
        + tuple(demon_name_texts(text_data))
        + tuple(f14_context_texts(text_data, slpm, f98))
        + EXTRA_STATIC_UI_CHARS
        + DIRECT_UI_F14_TEXTS
    ):
        chars = chars_of(text)
        used |= chars
        static |= chars

    # F14-only characters may spill onto reserved cells; everything above must
    # keep a real low code because it also appears in a dynamic-font screen.
    spillable = set()
    for text in f14_only_texts(text_data):
        chars = chars_of(text)
        used |= chars
        spillable |= chars
    spillable -= static
    static |= spillable

    for character in PINS.values():
        if character not in all_chars:
            raise SystemExit(f'pinned character missing from table: {character}')
    pinned = set(PINS.values()) | {SPACE}
    used -= pinned
    static -= pinned
    spillable -= pinned
    dynamic_only = used - static
    unused = all_chars - used - pinned

    reserved = set(DYNAMIC_SPECIAL_LOW_INDICES)
    cap = ORIGINAL_MAX_GLYPH_INDEX + 1
    taken = set(PINS) | {0}
    indices = [i for i in range(count) if i not in taken]
    low = [i for i in indices if i < cap and i not in reserved]
    high = [i for i in indices if i >= cap and i not in reserved]
    res = [i for i in indices if i in reserved]
    required = static - spillable
    if len(required) > len(low):
        raise SystemExit(
            f'dual-context static characters ({len(required)}) exceed low '
            f'slots ({len(low)})'
        )

    layout = {0: SPACE}
    layout.update(PINS)
    low_iter = iter(low)
    ordered = (
        sorted(required, key=lambda c: char2idx[c])
        + sorted(spillable, key=lambda c: char2idx[c])
    )
    spilled = []
    for character in ordered:
        index = next(low_iter, None)
        if index is None:
            spilled.append(character)
        else:
            layout[index] = character
    res_iter = iter(res)
    for character in spilled:
        layout[next(res_iter)] = character
    pool = iter(list(low_iter) + high + list(res_iter))
    for character in sorted(dynamic_only, key=lambda c: char2idx[c]):
        layout[next(pool)] = character
    remaining = [i for i in range(count) if i not in layout]
    for index, character in zip(
        remaining, sorted(unused, key=lambda c: char2idx[c])
    ):
        layout[index] = character

    if set(layout) != set(range(count)) or set(layout.values()) != all_chars:
        raise SystemExit('layout is not a bijection over the character set')

    if not BASELINE.is_file():
        shutil.copyfile(CODETABLE, BASELINE)
    shutil.copyfile(CODETABLE, str(CODETABLE) + '.bak')
    CODETABLE.write_text(
        json.dumps(
            {
                index.to_bytes(2, 'little').hex().upper(): character
                for index, character in sorted(layout.items())
            },
            ensure_ascii=False,
            indent=4,
        ),
        encoding='utf-8',
    )

    by_char = {c: i for i, c in layout.items()}
    overflow = sum(1 for c in used if by_char[c] in reserved)
    print(
        f'chars={count} used={len(used) + len(pinned)} static/F14={len(static)}'
        f' (dual-context {len(required)}, F14-only {len(spillable)},'
        f' spilled to reserved {len(spilled)})'
    )
    print(f'reserved-overflow (relocated at build time): {overflow}')
    print('pins: ' + ' '.join(f'{c}=0x{i:X}' for i, c in PINS.items()))
    print(f'wrote {CODETABLE}')


if __name__ == '__main__':
    main()
