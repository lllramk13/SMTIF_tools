import json
from dataclasses import dataclass
from pathlib import Path

from src.text_codec import encode_text, load_character_codes
from src.text_records import choose_text, load_text_data


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"
DEFAULT_TEXT_PATH = NEW_DIRECTORY / "data" / "text.json"
DEFAULT_MANIFEST_PATH = NEW_DIRECTORY / "build" / "static_text_aliases.json"

ORIGINAL_MAX_GLYPH_INDEX = 0x0566
STATIC_TEXT_SECTION = "text_17"
STATIC_TEXT_SECTIONS = (STATIC_TEXT_SECTION, "text_88")
STATIC_WIDTH = 0x0B


@dataclass(frozen=True)
class StaticTextAliasPlan:
    global_character_overrides: dict[str, bytes]
    section_character_overrides: dict[str, dict[str, bytes]]
    font_overrides: dict[int, str]
    width_table_overrides: dict[int, int]
    aliases: tuple[dict, ...]
    original_highest_index: int
    highest_index: int


def _code_to_index(code: str) -> int:
    code_bytes = bytes.fromhex(code)
    if len(code_bytes) != 2:
        raise ValueError(f"码表编号必须是两字节: {code!r}")
    return int.from_bytes(code_bytes, "little")


def _index_to_code(index: int) -> bytes:
    if not 0 <= index <= 0xFFFF:
        raise ValueError(f"字模编号超出两字节范围: {index:#x}")
    return index.to_bytes(2, "little")


def _glyph_indices(character_codes, text):
    encoded = encode_text(character_codes, text)
    indices = set()

    for position in range(0, len(encoded), 2):
        code = encoded[position:position + 2]
        if len(code) != 2 or code == b"\xFF\xFF":
            break

        # All IF control codes use FF as their second byte.  They are not
        # font glyphs and must not consume alias slots.
        if code[1] != 0xFF:
            indices.add(int.from_bytes(code, "little"))

    return indices


def build_static_width_overrides(width=STATIC_WIDTH):
    """Use a full-width advance for every glyph available in F14."""
    if not 0 <= width <= 0x0F:
        raise ValueError(f"Static glyph width is out of range: {width:#x}")
    return {
        glyph_index: width
        for glyph_index in range(ORIGINAL_MAX_GLYPH_INDEX + 1)
    }


def build_static_text_alias_plan(
    text_path=DEFAULT_TEXT_PATH,
    codetable_path=DEFAULT_CODETABLE_PATH,
):
    text_path = Path(text_path)
    codetable_path = Path(codetable_path)

    codetable = json.loads(codetable_path.read_text(encoding="utf-8"))
    index_to_character = {
        _code_to_index(code): character
        for code, character in codetable.items()
    }
    if not index_to_character:
        raise ValueError("码表为空")

    original_highest_index = max(index_to_character)
    expected_indices = set(range(original_highest_index + 1))
    if set(index_to_character) != expected_indices:
        raise ValueError("码表编号必须从0开始连续")

    character_codes = load_character_codes(codetable_path)
    text_data = load_text_data(text_path)
    section_indices = {}

    for section, records in text_data.items():
        indices = set()
        for record in records:
            indices.update(_glyph_indices(character_codes, choose_text(record)))
        section_indices[section] = indices

    static_indices = set().union(
        *(section_indices[section] for section in STATIC_TEXT_SECTIONS)
    )
    if static_indices is None:
        raise ValueError(f"文本中缺少 {STATIC_TEXT_SECTION!r} 分区")

    high_static_indices = sorted(
        index
        for index in static_indices
        if index > ORIGINAL_MAX_GLYPH_INDEX
    )
    low_candidates = sorted(
        set(range(1, ORIGINAL_MAX_GLYPH_INDEX + 1)) - static_indices,
        reverse=True,
    )

    if len(low_candidates) < len(high_static_indices):
        raise ValueError(
            f"静态文本需要 {len(high_static_indices)} 个低编号别名，"
            f"但只有 {len(low_candidates)} 个可搬移字位"
        )

    selected_low_indices = low_candidates[:len(high_static_indices)]
    next_high_index = original_highest_index + 1
    global_character_overrides = {}
    static_character_overrides = {}
    font_overrides = {}
    width_table_overrides = {}
    aliases = []

    for alias_offset, (target_index, low_index) in enumerate(
        zip(high_static_indices, selected_low_indices)
    ):
        moved_index = next_high_index + alias_offset
        target_character = index_to_character[target_index]
        moved_character = index_to_character[low_index]

        # Main text keeps the displaced character, but reads it from a new
        # high F13 slot.  Static F14 text sees the Chinese low-number alias.
        global_character_overrides[moved_character] = _index_to_code(moved_index)
        static_character_overrides[target_character] = _index_to_code(low_index)

        font_overrides[low_index] = target_character
        font_overrides[moved_index] = moved_character
        width_table_overrides[low_index] = STATIC_WIDTH

        aliases.append({
            "menu_character": target_character,
            "normal_code": f"{target_index:04X}",
            "menu_code": f"{low_index:04X}",
            "moved_character": moved_character,
            "moved_from": f"{low_index:04X}",
            "moved_to": f"{moved_index:04X}",
        })

    highest_index = (
        next_high_index + len(aliases) - 1
        if aliases
        else original_highest_index
    )

    return StaticTextAliasPlan(
        global_character_overrides=global_character_overrides,
        section_character_overrides={
            section: dict(static_character_overrides)
            for section in STATIC_TEXT_SECTIONS
        },
        font_overrides=font_overrides,
        width_table_overrides=width_table_overrides,
        aliases=tuple(aliases),
        original_highest_index=original_highest_index,
        highest_index=highest_index,
    )


def write_alias_manifest(plan, output_path=DEFAULT_MANIFEST_PATH):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "alias_count": len(plan.aliases),
        "original_highest_index": f"{plan.original_highest_index:04X}",
        "highest_index": f"{plan.highest_index:04X}",
        "aliases": list(plan.aliases),
    }
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output_path


if __name__ == "__main__":
    alias_plan = build_static_text_alias_plan()
    manifest_path = write_alias_manifest(alias_plan)
    print(f"Static aliases: {len(alias_plan.aliases)}")
    print(f"Highest F13 index: 0x{alias_plan.highest_index:04X}")
    print(f"Manifest: {manifest_path}")
