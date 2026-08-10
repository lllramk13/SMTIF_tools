import json
from pathlib import Path

from src.glyph_layout import DYNAMIC_SPECIAL_LOW_INDICES
from src.mixed_name_layout import ORIGINAL_FULLWIDTH_LATIN_INDICES


HERE = Path(__file__).resolve().parent
DEFAULT_CODETABLE_PATH = (
    HERE.parent / "data" / "original_ui_codetable.json"
)


def load_original_ui_glyph_overrides(path=DEFAULT_CODETABLE_PATH):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    overrides = {}

    for code, character in data.items():
        code_bytes = bytes.fromhex(code)
        if len(code_bytes) != 2:
            raise ValueError(f"Invalid original UI code: {code!r}")
        index = int.from_bytes(code_bytes, "little")
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(
                f"Original UI glyph {index:#x} must be one character"
            )
        overrides[index] = character

    latin_mismatches = [
        (index, overrides.get(index), character)
        for character, index in ORIGINAL_FULLWIDTH_LATIN_INDICES.items()
        if overrides.get(index) != character
    ]
    if latin_mismatches:
        raise ValueError(
            "Original UI glyph table no longer contains A-Z at "
            "0x034..0x04D: "
            + " ".join(
                f"{index:#x}={actual!r}/{expected!r}"
                for index, actual, expected in latin_mismatches[:8]
            )
        )

    # The table still lists every cell the original UI alphabet used, including
    # the released kana block.  Only the cells that are still reserved may be
    # painted back over the translated font; the rest now hold real Chinese.
    missing = sorted(set(DYNAMIC_SPECIAL_LOW_INDICES) - set(overrides))
    if missing:
        raise ValueError(
            "Original UI glyph table is missing reserved cells: "
            f"{[hex(index) for index in missing[:8]]}"
        )

    return {
        index: character
        for index, character in overrides.items()
        if index in DYNAMIC_SPECIAL_LOW_INDICES
    }
