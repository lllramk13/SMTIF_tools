"""Build the Chinese name-entry keyboard and validate its hardwired codes.

The visible keyboard lives in F0073, but the game does not read the selected
character code back from that graphic or from F0082.  Each cell still returns
its original hardwired code in 0x068..0x107.  The effective codetable must
therefore place each selected Chinese character at that exact source code.

F0082 is a Japanese input-method page table, not the direct keyboard return
table.  It is kept in sync for completeness, but changing F0082 alone does not
change what the name-entry grid inserts.

Only the 16 x 10 kana area is replaced.  The three right-hand columns contain
digits, Latin letters and command keys and remain byte-for-byte original.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from src.compression import compress_rle
from src.font_builder import load_codetable
from src.glyph_layout import DYNAMIC_SPECIAL_LOW_INDICES
from src.graphic_resource import (
    decompress_graphic_resource,
    pack_4bpp_pixels,
    unpack_4bpp_pixels,
)
from src.static_font_resource import (
    CELL_HEIGHT,
    CELL_WIDTH,
    GLYPHS_PER_PLANE,
    ROWS_PER_COLUMN,
)


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
PROJECT_DIRECTORY = NEW_DIRECTORY.parent

DEFAULT_CHARACTER_PATH = NEW_DIRECTORY / "data" / "name_entry_characters.json"
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"
ORIGINAL_F73_PATH = PROJECT_DIRECTORY / "extrac" / "D" / "F0073.BIN"
OUTPUT_F73_PATH = NEW_DIRECTORY / "build" / "F0073.BIN"
OUTPUT_F82_PATH = NEW_DIRECTORY / "build" / "F0082.BIN"

KEYBOARD_ROWS = 16
CHINESE_COLUMNS = 10
GRID_COLUMNS = 13
F73_WIDTH = GRID_COLUMNS * CELL_WIDTH
F73_HEIGHT = 208
F14_GLYPH_COUNT = 0x0567
SECOND_F73_RESOURCE_OFFSET = 0x3800

# Original codes behind the left 10 cells of every visible keyboard row.
# This is the screen order, not numeric order.  Together they are exactly
# 0x068..0x107, once each.
SOURCE_CODE_ROWS = (
    (0x069, 0x06B, 0x06D, 0x06F, 0x071, 0x0B9, 0x0BB, 0x0BD, 0x0BF, 0x0C1),
    (0x072, 0x074, 0x076, 0x078, 0x07A, 0x0C2, 0x0C4, 0x0C6, 0x0C8, 0x0CA),
    (0x07C, 0x07E, 0x080, 0x082, 0x084, 0x0CC, 0x0CE, 0x0D0, 0x0D2, 0x0D4),
    (0x086, 0x088, 0x08B, 0x08D, 0x08F, 0x0D6, 0x0D8, 0x0DB, 0x0DD, 0x0DF),
    (0x091, 0x092, 0x093, 0x094, 0x095, 0x0E1, 0x0E2, 0x0E3, 0x0E4, 0x0E5),
    (0x096, 0x099, 0x09C, 0x09F, 0x0A2, 0x0E6, 0x0E9, 0x0EC, 0x0EF, 0x0F2),
    (0x0A5, 0x0A6, 0x0A7, 0x0A8, 0x0A9, 0x0F5, 0x0F6, 0x0F7, 0x0F8, 0x0F9),
    (0x0B0, 0x0B1, 0x0B2, 0x0B3, 0x0B4, 0x100, 0x101, 0x102, 0x103, 0x104),
    (0x0AB, 0x0AD, 0x0AF, 0x0B5, 0x0B6, 0x0FB, 0x0FD, 0x0FF, 0x105, 0x106),
    (0x0B7, 0x068, 0x06A, 0x06C, 0x06E, 0x107, 0x0B8, 0x0BA, 0x0BC, 0x0BE),
    (0x070, 0x08A, 0x0AA, 0x0AC, 0x0AE, 0x0C0, 0x0DA, 0x0FA, 0x0FC, 0x0FE),
    (0x073, 0x075, 0x077, 0x079, 0x07B, 0x0C3, 0x0C5, 0x0C7, 0x0C9, 0x0CB),
    (0x07D, 0x07F, 0x081, 0x083, 0x085, 0x0CD, 0x0CF, 0x0D1, 0x0D3, 0x0D5),
    (0x087, 0x089, 0x08C, 0x08E, 0x090, 0x0D7, 0x0D9, 0x0DC, 0x0DE, 0x0E0),
    (0x097, 0x09A, 0x09D, 0x0A0, 0x0A3, 0x0E7, 0x0EA, 0x0ED, 0x0F0, 0x0F3),
    (0x098, 0x09B, 0x09E, 0x0A1, 0x0A4, 0x0E8, 0x0EB, 0x0EE, 0x0F1, 0x0F4),
)


@dataclass(frozen=True)
class NameEntryPlan:
    rows: tuple[str, ...]
    characters: tuple[str, ...]
    source_codes: tuple[int, ...]
    target_codes: tuple[int, ...]
    source_to_target: dict[int, int]


def _flatten(rows):
    return tuple(value for row in rows for value in row)


def build_name_entry_plan(
    character_path=DEFAULT_CHARACTER_PATH,
    codetable_path=DEFAULT_CODETABLE_PATH,
):
    """Load and validate the 160-character Chinese keyboard layout."""
    character_path = Path(character_path)
    with character_path.open("r", encoding="utf-8") as json_file:
        document = json.load(json_file)

    if not isinstance(document, dict) or not isinstance(
        document.get("rows"), list
    ):
        raise ValueError("Name-entry JSON must contain a rows list")

    rows = tuple(document["rows"])
    if len(rows) != KEYBOARD_ROWS:
        raise ValueError(
            f"Name-entry keyboard needs {KEYBOARD_ROWS} rows, got {len(rows)}"
        )
    for row_number, row in enumerate(rows):
        if not isinstance(row, str) or len(row) != CHINESE_COLUMNS:
            raise ValueError(
                f"Name-entry row {row_number} must contain exactly "
                f"{CHINESE_COLUMNS} characters"
            )

    characters = _flatten(rows)
    if len(set(characters)) != len(characters):
        duplicates = sorted(
            character
            for character in set(characters)
            if characters.count(character) > 1
        )
        raise ValueError(
            f"Name-entry characters must be unique: {duplicates[:8]}"
        )

    codetable = load_codetable(codetable_path)
    character_to_index = {
        character: index for index, character in codetable.items()
    }
    target_codes = []
    for character in characters:
        index = character_to_index.get(character)
        if index is None:
            raise ValueError(
                f"Name-entry character is absent from codetable: {character}"
            )
        if index >= F14_GLYPH_COUNT:
            raise ValueError(
                f"Name-entry character {character} uses high code {index:#x}; "
                "the name screen can only draw F14 low codes"
            )
        if index in DYNAMIC_SPECIAL_LOW_INDICES:
            raise ValueError(
                f"Name-entry character {character} uses reserved UI code "
                f"{index:#x}"
            )
        target_codes.append(index)

    source_codes = _flatten(SOURCE_CODE_ROWS)
    expected_source_codes = set(range(0x068, 0x108))
    if set(source_codes) != expected_source_codes:
        raise AssertionError(
            "Name-entry source grid is not a permutation of 0x068..0x107"
        )

    mismatches = [
        (character, source_code, target_code)
        for character, source_code, target_code
        in zip(characters, source_codes, target_codes)
        if source_code != target_code
    ]
    if mismatches:
        examples = ", ".join(
            f"{character}: key {source_code:#x}, codetable {target_code:#x}"
            for character, source_code, target_code in mismatches[:8]
        )
        raise ValueError(
            "Name-entry codetable is not aligned with the grid's hardwired "
            f"return codes ({len(mismatches)} mismatch(es)): {examples}"
        )

    source_to_target = dict(zip(source_codes, target_codes))
    if len(source_to_target) != KEYBOARD_ROWS * CHINESE_COLUMNS:
        raise AssertionError("Name-entry source mapping is not one-to-one")

    return NameEntryPlan(
        rows=rows,
        characters=characters,
        source_codes=source_codes,
        target_codes=tuple(target_codes),
        source_to_target=source_to_target,
    )


def validate_f14_plan(
    plan,
    codetable_path=DEFAULT_CODETABLE_PATH,
    glyph_overrides=None,
):
    """Assert that every selected code actually paints its selected character."""
    final_glyphs = load_codetable(codetable_path)
    final_glyphs.update(glyph_overrides or {})

    for character, index in zip(plan.characters, plan.target_codes):
        actual = final_glyphs.get(index)
        if actual != character:
            raise ValueError(
                f"Name-entry key {character} uses {index:#x}, but final F14 "
                f"would paint {actual!r}"
            )


def patch_f0082(file_data, plan, output_path=OUTPUT_F82_PATH):
    """Keep the Japanese IME pages aligned with the Chinese keyboard codes."""
    file_data = bytes(file_data)
    if len(file_data) < 8 or file_data[:2] != b"\x01\x00":
        raise ValueError("F0082 is not the expected uncompressed resource")

    declared_size = int.from_bytes(file_data[4:8], "little")
    if not 8 <= declared_size <= len(file_data):
        raise ValueError(f"F0082 has invalid declared size {declared_size:#x}")

    patched = bytearray(file_data)
    touched_offsets = set()
    for source_code, target_code in plan.source_to_target.items():
        group = source_code // 16
        column = source_code % 16
        pointer_offset = 8 + group * 4
        if pointer_offset + 4 > declared_size:
            raise ValueError("F0082 pointer table ends before the kana pages")

        relative_string_offset = int.from_bytes(
            file_data[pointer_offset:pointer_offset + 4],
            "little",
        )
        # F0082 pointers are relative to the byte immediately after the
        # resource's 8-byte header, not to the start of the file.
        string_offset = 8 + relative_string_offset
        code_offset = string_offset + column * 2
        terminator_offset = string_offset + 16 * 2
        if terminator_offset + 2 > declared_size:
            raise ValueError(
                f"F0082 page {group:#x} lies outside the declared resource"
            )
        if file_data[terminator_offset:terminator_offset + 2] != b"\xFF\xFF":
            raise ValueError(
                f"F0082 page {group:#x} is not a 16-code page"
            )

        patched[code_offset:code_offset + 2] = target_code.to_bytes(
            2, "little"
        )
        touched_offsets.add(code_offset)

    if len(touched_offsets) != KEYBOARD_ROWS * CHINESE_COLUMNS:
        raise AssertionError("F0082 patch did not touch 160 distinct entries")
    if len(patched) != len(file_data):
        raise AssertionError("F0082 patch changed the file length")

    for source_code, target_code in plan.source_to_target.items():
        group = source_code // 16
        column = source_code % 16
        relative_string_offset = int.from_bytes(
            patched[8 + group * 4:12 + group * 4],
            "little",
        )
        string_offset = 8 + relative_string_offset
        actual = int.from_bytes(
            patched[
                string_offset + column * 2:
                string_offset + column * 2 + 2
            ],
            "little",
        )
        if actual != target_code:
            raise AssertionError("F0082 name-entry verification failed")

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(patched)

    print("F0082 Chinese name-entry codes patched: 160")
    return bytes(patched)


def _static_glyph_bitmap(pixels, width, code):
    plane = code // GLYPHS_PER_PLANE
    slot = code % GLYPHS_PER_PLANE
    origin_x = slot // ROWS_PER_COLUMN * CELL_WIDTH
    origin_y = slot % ROWS_PER_COLUMN * CELL_HEIGHT
    plane_mask = 1 << plane

    return tuple(
        tuple(
            bool(pixels[(origin_y + y) * width + origin_x + x] & plane_mask)
            for x in range(CELL_WIDTH)
        )
        for y in range(CELL_HEIGHT)
    )


def _build_name_entry_pixels(f14_pixels, f14_width, original_f73_pixels, plan):
    pixels = bytearray(original_f73_pixels)

    for row in range(KEYBOARD_ROWS):
        for column in range(CHINESE_COLUMNS):
            target_code = plan.target_codes[
                row * CHINESE_COLUMNS + column
            ]
            bitmap = _static_glyph_bitmap(
                f14_pixels,
                f14_width,
                target_code,
            )
            origin_x = column * CELL_WIDTH
            origin_y = row * CELL_HEIGHT

            for y in range(CELL_HEIGHT):
                for x in range(CELL_WIDTH):
                    pixel_offset = (
                        (origin_y + y) * F73_WIDTH + origin_x + x
                    )
                    # Bit 0 is the white glyph and bit 1 its grey shadow.
                    # Dense Chinese glyphs fit reliably without the shadow.
                    # Bits 2/3 belong to the original background and survive.
                    pixels[pixel_offset] &= 0x0C
                    if bitmap[y][x]:
                        pixels[pixel_offset] |= 0x01

    # Prove that the right-hand controls and the unused bottom strip did not
    # change while the Chinese area was repainted.
    for y in range(F73_HEIGHT):
        for x in range(F73_WIDTH):
            if x < CHINESE_COLUMNS * CELL_WIDTH and y < (
                KEYBOARD_ROWS * CELL_HEIGHT
            ):
                continue
            offset = y * F73_WIDTH + x
            if pixels[offset] != original_f73_pixels[offset]:
                raise AssertionError(
                    "F0073 rebuild changed a non-Chinese keyboard pixel"
                )

    return bytes(pixels)


def _align_to_4(value):
    return (value + 3) & ~3


def _build_variable_size_graphic(original_graphic, raw_data):
    generic_rle = compress_rle(raw_data)
    payload = generic_rle[12:]
    declared_size = 16 + len(payload)
    header = b"".join((
        original_graphic.resource_header,
        declared_size.to_bytes(4, "little"),
        original_graphic.reserved,
        original_graphic.width_words.to_bytes(2, "little"),
        original_graphic.height.to_bytes(2, "little"),
    ))
    return header + payload


def build_f0073(
    f14_data,
    plan,
    original_f73_path=ORIGINAL_F73_PATH,
    output_path=OUTPUT_F73_PATH,
):
    """Repaint the visible 16 x 10 kana atlas with the selected Chinese glyphs."""
    f14 = decompress_graphic_resource(f14_data)
    f14_pixels = unpack_4bpp_pixels(
        f14.raw_data,
        f14.pixel_width,
        f14.height,
    )

    original_file = Path(original_f73_path).read_bytes()
    original_f73 = decompress_graphic_resource(original_file)
    if (
        original_f73.pixel_width != F73_WIDTH
        or original_f73.height != F73_HEIGHT
    ):
        raise ValueError(
            f"Unexpected F0073 geometry {original_f73.pixel_width}x"
            f"{original_f73.height}"
        )

    original_pixels = unpack_4bpp_pixels(
        original_f73.raw_data,
        original_f73.pixel_width,
        original_f73.height,
    )
    rebuilt_pixels = _build_name_entry_pixels(
        f14_pixels,
        f14.pixel_width,
        original_pixels,
        plan,
    )
    rebuilt_raw = pack_4bpp_pixels(
        rebuilt_pixels,
        original_f73.pixel_width,
        original_f73.height,
    )
    main_resource = _build_variable_size_graphic(
        original_f73,
        rebuilt_raw,
    )

    original_palette_offset = _align_to_4(original_f73.declared_size)
    palette_size = int.from_bytes(
        original_file[
            original_palette_offset + 4:original_palette_offset + 8
        ],
        "little",
    )
    if palette_size < 8:
        raise ValueError("F0073 palette has an invalid resource size")
    palette = original_file[
        original_palette_offset:original_palette_offset + palette_size
    ]
    palette_offset = _align_to_4(len(main_resource))
    palette_end = palette_offset + len(palette)
    if palette_end > SECOND_F73_RESOURCE_OFFSET:
        raise ValueError(
            f"Chinese F0073 main resource and palette end at "
            f"{palette_end:#x}, past the next resource at "
            f"{SECOND_F73_RESOURCE_OFFSET:#x}"
        )

    rebuilt_file = b"".join((
        main_resource,
        bytes(palette_offset - len(main_resource)),
        palette,
        bytes(SECOND_F73_RESOURCE_OFFSET - palette_end),
        original_file[SECOND_F73_RESOURCE_OFFSET:],
    ))
    if len(rebuilt_file) != len(original_file):
        raise AssertionError("F0073 rebuild changed the file length")
    if (
        rebuilt_file[SECOND_F73_RESOURCE_OFFSET:]
        != original_file[SECOND_F73_RESOURCE_OFFSET:]
    ):
        raise AssertionError("F0073 rebuild changed later resources")

    verified = decompress_graphic_resource(rebuilt_file)
    if verified.raw_data != rebuilt_raw:
        raise AssertionError("F0073 decompression verification failed")

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(rebuilt_file)

    print("F0073 Chinese name-entry cells rendered: 160")
    print(
        f"F0073 main block: {len(main_resource):#x}; "
        f"palette moved to {palette_offset:#x}"
    )
    return rebuilt_file
