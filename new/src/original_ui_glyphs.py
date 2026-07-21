import json
from pathlib import Path

from src.dynamic_low_code_relocation import DYNAMIC_SPECIAL_LOW_INDICES


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

    actual_indices = set(overrides)
    if actual_indices != set(DYNAMIC_SPECIAL_LOW_INDICES):
        missing = sorted(DYNAMIC_SPECIAL_LOW_INDICES - actual_indices)
        extra = sorted(actual_indices - DYNAMIC_SPECIAL_LOW_INDICES)
        raise ValueError(
            "Original UI glyph table does not match the reserved range; "
            f"missing={missing[:8]}, extra={extra[:8]}"
        )

    return overrides
