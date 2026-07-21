from dataclasses import dataclass
from pathlib import Path

from src.font_builder import load_codetable


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"

EXPANDED_GLYPH_COUNT = 0x0ACE

# These low codes are used by the original name-entry/one-byte UI paths.
# Normal translated dialogue must not rely on their direct low-code meaning.
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


@dataclass(frozen=True)
class DynamicLowCodeRelocationPlan:
    character_code_overrides: dict[str, bytes]
    static_character_code_overrides: dict[str, bytes]
    font_overrides: dict[int, str]
    aliases: tuple[dict, ...]
    highest_index: int


def build_dynamic_low_code_relocation_plan(
    first_free_index,
    codetable_path=DEFAULT_CODETABLE_PATH,
):
    codetable = load_codetable(codetable_path)
    missing = sorted(DYNAMIC_SPECIAL_LOW_INDICES - codetable.keys())
    if missing:
        raise ValueError(
            f"Special low codes are missing from the codetable: {missing[:8]}"
        )

    first_free_index = int(first_free_index)
    final_index = first_free_index + len(DYNAMIC_SPECIAL_LOW_INDICES) - 1
    if final_index >= EXPANDED_GLYPH_COUNT:
        raise ValueError(
            f"Dynamic relocation needs glyph 0x{final_index:04X}, but the "
            f"expanded F13 ends at 0x{EXPANDED_GLYPH_COUNT - 1:04X}"
        )

    character_code_overrides = {}
    static_character_code_overrides = {}
    font_overrides = {}
    aliases = []

    for offset, original_index in enumerate(sorted(DYNAMIC_SPECIAL_LOW_INDICES)):
        relocated_index = first_free_index + offset
        character = codetable[original_index]

        # Normal dialogue uses the high F13 copy.  Static text_17/text_88
        # keeps using the original low F14 cell.  Crucially, the low glyph is
        # not replaced with an original Japanese/name glyph.
        character_code_overrides[character] = relocated_index.to_bytes(
            2, "little"
        )
        static_character_code_overrides[character] = original_index.to_bytes(
            2, "little"
        )
        font_overrides[relocated_index] = character
        aliases.append({
            "character": character,
            "normal_from": f"{original_index:04X}",
            "normal_to": f"{relocated_index:04X}",
            "static_code": f"{original_index:04X}",
        })

    return DynamicLowCodeRelocationPlan(
        character_code_overrides=character_code_overrides,
        static_character_code_overrides=static_character_code_overrides,
        font_overrides=font_overrides,
        aliases=tuple(aliases),
        highest_index=final_index,
    )
