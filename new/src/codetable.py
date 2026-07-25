import json
from collections import Counter
from pathlib import Path

# file locations
current_dir = Path(__file__).resolve().parent
LEGACY_CODETABLE_PATH = (
    current_dir.parent.parent / 'PreWork' / 'if备案' / '导入码表.tbl'
)
CODETABLE_JSON_PATH = current_dir.parent / 'data' / 'codetable.json'

NEW_CODETABLE_ENTRIES = {
    '9509': '勿',
    '9609': '储',
    '9709': '《',
    '9809': 'i',
    '9909': 'f',
    '9A09': '》',
    # Added 2026-07-21 for the F0098 race/item-category name-table translation.
    '9F09': '辅',
    'A009': '槽',
    'A109': '页',
    'A209': '循',
    'A309': '框',
    'A409': '哑',
    # Added 2026-07-25 for the F0049/F0092 overlay translation.
    'A509': '鉴',
    'A609': '例',
    'A709': '旧',
    'A809': '骇',
    'A909': '幻',
    'AA09': '骑',
    'AB09': '贩',
}

CONTROL_MARKERS = [
    "※※※※※※※",
    "{主角等人}",
    "{大停顿}",
    "{数值0}",
    "{数值1}",
    "{名字1}",
    "{名字2}",
    "{名字3}",
    "{名字4}",
    "{种族1}",
    "{种族2}",
    "{种族3}",
    "{恶魔1}",
    "{恶魔2}",
    "{00FF}",
    "{队友}",
    "{主角}",
    "{道具}",
    "{仲魔}",
    "{魔法}",
    "{数量}",
    "{72FF}}",
    "{73FF}}",
    "▽",
    "/",
    "　",
    "\n",
    "\r",
]


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def convert_legacy_table_to_json(
    table_path=LEGACY_CODETABLE_PATH,
    output_path=CODETABLE_JSON_PATH,
):
    """Convert the predecessor's UTF-16 table to a hex-to-character JSON map."""
    table_path = Path(table_path)
    output_path = Path(output_path)
    codetable = {}
    character_codes = {}

    with table_path.open('r', encoding='utf-16') as table_file:
        for line_number, raw_line in enumerate(table_file, start=1):
            line = raw_line.strip('\r\n')
            if not line:
                continue
            if '=' not in line:
                raise ValueError(
                    f'Invalid table entry at line {line_number}: {line!r}'
                )

            code, character = line.split('=', 1)
            code = code.strip().upper()

            try:
                code_bytes = bytes.fromhex(code)
            except ValueError as error:
                raise ValueError(
                    f'Invalid hex code at line {line_number}: {code!r}'
                ) from error

            if len(code_bytes) != 2:
                raise ValueError(
                    f'Code must contain exactly two bytes at line '
                    f'{line_number}: {code!r}'
                )

            # Empty entries are unused capacity in the old table, not glyphs.
            if not character:
                continue
            if code in codetable:
                raise ValueError(f'Duplicate code in legacy table: {code}')
            if character in character_codes:
                raise ValueError(
                    f'Duplicate character in legacy table: {character!r}'
                )

            codetable[code] = character
            character_codes[character] = code

    for code, character in NEW_CODETABLE_ENTRIES.items():
        if code in codetable:
            raise ValueError(f'New code is already occupied: {code}')
        if character in character_codes:
            raise ValueError(
                f'New character already exists as {character_codes[character]}: '
                f'{character!r}'
            )
        codetable[code] = character
        character_codes[character] = code

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, codetable)
    return codetable


def remove_control_marker(text: str) -> str:
    for marker in CONTROL_MARKERS:
        text = str(text).replace(marker, "")
    return text



