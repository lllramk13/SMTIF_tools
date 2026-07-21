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

from src.dynamic_low_code_relocation import DYNAMIC_SPECIAL_LOW_INDICES
from src.static_text_aliases import (
    ORIGINAL_MAX_GLYPH_INDEX,
    STATIC_TEXT_SECTIONS,
    _glyph_indices,
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
            for i in _glyph_indices(character_codes, text)
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
