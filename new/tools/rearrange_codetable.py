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
from src.font_builder import load_codetable

CODETABLE = NEW_DIR / 'data' / 'codetable.json'
BASELINE = NEW_DIR / 'data' / 'codetable.json.prerearrange.bak'

SPACE = '　'
# Hardcoded stat-abbreviation codes (SLPM table at 0xE5C20 stores these glyph
# indices directly).  executable_patch.py changes the last entry from the
# original 運=0x131 to the simplified Chinese 运=0x180.
PINS = {0x53B: '力', 0x3CD: '知', 0x4D2: '魔', 0x3A8: '体', 0x39A: '速', 0x180: '运'}
# Preset partner names shown in the party panel.
PARTY_PRESET_NAMES = ('由美', '查理', '明')
# Hardcoded single glyphs patched into the executable at build time
# (executable_patch.py resolves their codes from the codetable): 智 replaces
# the intelligence stat's 知, 等 is the name-plural suffix (達 -> 等).  Both
# render via F14, so they must stay below 0x567.
EXTRA_STATIC_UI_CHARS = ('智', '等')
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
    for text in (
        translated_slpm_texts(slpm, 'static')
        + translated_f0098_texts(f98)
        + tuple(party_name_texts(text_data))
        + tuple(item_name_texts(text_data))
        # menu_option_texts() / skill_name_texts() are intentionally handled
        # by src/f14_context_aliases.py instead of consuming globally unique
        # low codes.  Their F14-only records reuse original name-entry cells;
        # keyboard-entered names are routed back to the original small font.
        + EXTRA_STATIC_UI_CHARS
    ):
        chars = chars_of(text)
        used |= chars
        static |= chars

    for character in PINS.values():
        if character not in all_chars:
            raise SystemExit(f'pinned character missing from table: {character}')
    pinned = set(PINS.values()) | {SPACE}
    used -= pinned
    static -= pinned
    dynamic_only = used - static
    unused = all_chars - used - pinned

    reserved = set(DYNAMIC_SPECIAL_LOW_INDICES)
    cap = ORIGINAL_MAX_GLYPH_INDEX + 1
    taken = set(PINS) | {0}
    indices = [i for i in range(count) if i not in taken]
    low = [i for i in indices if i < cap and i not in reserved]
    high = [i for i in indices if i >= cap and i not in reserved]
    res = [i for i in indices if i in reserved]
    if len(static) > len(low):
        raise SystemExit(
            f'static/F14 characters ({len(static)}) exceed low slots ({len(low)})'
        )

    layout = {0: SPACE}
    layout.update(PINS)
    low_iter = iter(low)
    for character in sorted(static, key=lambda c: char2idx[c]):
        layout[next(low_iter)] = character
    pool = iter(list(low_iter) + high + res)
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
    print(f'chars={count} used={len(used) + len(pinned)} static/F14={len(static)}')
    print(f'reserved-overflow (relocated at build time): {overflow}')
    print('pins: ' + ' '.join(f'{c}=0x{i:X}' for i, c in PINS.items()))
    print(f'wrote {CODETABLE}')


if __name__ == '__main__':
    main()
