from pathlib import Path

from src.compression import compress_rle
from src.font_builder import BYTES_PER_GLYPH, GLYPH_H, GLYPH_W
from src.graphic_resource import (
    decompress_graphic_resource,
    pack_4bpp_pixels,
    rebuild_graphic_resource,
    unpack_4bpp_pixels,
)


HERE = Path(__file__).resolve().parent
PROJECT_DIRECTORY = HERE.parent.parent
RAW_FONT_PATH = HERE.parent / "build" / "font_1bpp.bin"
ORIGINAL_F14_PATH = PROJECT_DIRECTORY / "extrac" / "D" / "F0014.BIN"
OUTPUT_F14_PATH = HERE.parent / "build" / "F0014.BIN"

# F14 is 208x252 = 17 columns x 21 rows = 357 cells per bit plane, of which the
# game uses 346 -> 4*346-1 = 0x567 glyphs.  Widening it was investigated at
# length and is NOT possible; see F14_CAPACITY_RE.md for the full write-up:
#   * more glyphs = more ink = worse RLE, so even +44 glyphs pushes the texture
#     past F0014.BIN's fixed 24576-byte slot (23801 vs a 23538 budget);
#   * the file cannot move, because FILEPOS.DAT -- the game's own file table --
#     requires every file to stay contiguous and ascending by LBA, and a full
#     disc re-layout cannot be shown to be safe against hardcoded LBAs.
# So the capacity really is fixed at 1383.  src/f14_context_aliases.py keeps
# the texture at that size by reusing 22 cells released through the mixed-name
# global encoding policy, while the original A-Z cells remain readable in F14.
ORIGINAL_PIXEL_WIDTH = 208
GLYPHS_PER_PLANE = 346
PLANE_COUNT = 4
STATIC_GLYPH_COUNT = 0x0567
CELL_WIDTH = 12
CELL_HEIGHT = 12
ROWS_PER_COLUMN = 21
EXPECTED_PIXEL_WIDTH = 208
EXPECTED_HEIGHT = 252


def _glyph_pixel_is_ink(glyph, x, y):
    """Return True for an ink pixel in IF's inverted packed 1bpp format."""
    byte_value = glyph[y * 2 + x // 8]
    return not byte_value & (1 << (x % 8))


def widen_original_pixels(original_pixels, width, height):
    """Pass the original texture through (kept for the widening experiment)."""
    if width != ORIGINAL_PIXEL_WIDTH or height != EXPECTED_HEIGHT:
        raise ValueError(
            f"Unexpected original F14 dimensions {width}x{height}; expected "
            f"{ORIGINAL_PIXEL_WIDTH}x{EXPECTED_HEIGHT}"
        )
    if len(original_pixels) != width * height:
        raise ValueError(
            f"F14 pixel buffer has {len(original_pixels)} entries; expected "
            f"{width * height}"
        )

    if EXPECTED_PIXEL_WIDTH == width:
        return bytes(original_pixels)
    widened = bytearray(EXPECTED_PIXEL_WIDTH * height)
    for y in range(height):
        widened[y * EXPECTED_PIXEL_WIDTH:y * EXPECTED_PIXEL_WIDTH + width] = (
            original_pixels[y * width:(y + 1) * width]
        )
    return bytes(widened)


def build_static_font_pixels(font_data, original_pixels, width, height):
    """Overlay the first STATIC_GLYPH_COUNT glyphs into F14's four bit planes."""
    font_data = bytes(font_data)
    pixels = bytearray(original_pixels)

    required_font_size = STATIC_GLYPH_COUNT * BYTES_PER_GLYPH
    if len(font_data) < required_font_size:
        raise ValueError(
            f"Static font needs at least {required_font_size} bytes, "
            f"got {len(font_data)}"
        )
    if GLYPH_W < CELL_WIDTH or GLYPH_H != CELL_HEIGHT:
        raise ValueError(
            f"Font glyph geometry {GLYPH_W}x{GLYPH_H} cannot fill "
            f"{CELL_WIDTH}x{CELL_HEIGHT} static cells"
        )
    if width != EXPECTED_PIXEL_WIDTH or height != EXPECTED_HEIGHT:
        raise ValueError(
            f"Unexpected F14 dimensions {width}x{height}; expected "
            f"{EXPECTED_PIXEL_WIDTH}x{EXPECTED_HEIGHT}"
        )
    if len(pixels) != width * height:
        raise ValueError(
            f"F14 pixel buffer has {len(pixels)} entries; expected "
            f"{width * height}"
        )
    last_column_end = (
        (GLYPHS_PER_PLANE - 1) // ROWS_PER_COLUMN * CELL_WIDTH + CELL_WIDTH
    )
    if last_column_end > width:
        raise ValueError(
            f"{GLYPHS_PER_PLANE} glyphs/plane need {last_column_end}px of "
            f"width; the texture only has {width}px"
        )

    for glyph_index in range(STATIC_GLYPH_COUNT):
        plane = glyph_index // GLYPHS_PER_PLANE
        slot = glyph_index % GLYPHS_PER_PLANE
        origin_x = slot // ROWS_PER_COLUMN * CELL_WIDTH
        origin_y = slot % ROWS_PER_COLUMN * CELL_HEIGHT
        plane_mask = 1 << plane
        inverse_mask = 0x0F ^ plane_mask

        glyph_start = glyph_index * BYTES_PER_GLYPH
        glyph = font_data[glyph_start:glyph_start + BYTES_PER_GLYPH]

        for y in range(CELL_HEIGHT):
            row_start = (origin_y + y) * width + origin_x
            for x in range(CELL_WIDTH):
                pixel_offset = row_start + x
                if _glyph_pixel_is_ink(glyph, x, y):
                    pixels[pixel_offset] |= plane_mask
                else:
                    pixels[pixel_offset] &= inverse_mask

    return bytes(pixels)


def build_f14(
    raw_font_path=RAW_FONT_PATH,
    original_f14_path=ORIGINAL_F14_PATH,
    output_path=OUTPUT_F14_PATH,
):
    raw_font_path = Path(raw_font_path)
    original_f14_path = Path(original_f14_path)
    output_path = Path(output_path)

    font_data = raw_font_path.read_bytes()
    original_f14 = original_f14_path.read_bytes()
    graphic = decompress_graphic_resource(original_f14)
    original_pixels = unpack_4bpp_pixels(
        graphic.raw_data,
        graphic.pixel_width,
        graphic.height,
    )
    widened_pixels = widen_original_pixels(
        original_pixels,
        graphic.pixel_width,
        graphic.height,
    )
    rebuilt_pixels = build_static_font_pixels(
        font_data,
        widened_pixels,
        EXPECTED_PIXEL_WIDTH,
        graphic.height,
    )
    rebuilt_raw_data = pack_4bpp_pixels(
        rebuilt_pixels,
        EXPECTED_PIXEL_WIDTH,
        graphic.height,
    )
    # compress_rle() includes the generic resource's 12-byte header; F14 uses
    # a 16-byte graphic header around the same token stream.
    minimum_main_block_size = len(compress_rle(rebuilt_raw_data)) + 4
    if minimum_main_block_size > graphic.declared_size:
        raise ValueError(
            f"F0014 minimum RLE block is {minimum_main_block_size} bytes, "
            f"but the fixed budget is {graphic.declared_size} bytes"
        )
    rle_margin = graphic.declared_size - minimum_main_block_size
    rebuilt_f14 = rebuild_graphic_resource(
        original_f14,
        rebuilt_raw_data,
    )

    rebuilt_graphic = decompress_graphic_resource(rebuilt_f14)
    if rebuilt_graphic.pixel_width != EXPECTED_PIXEL_WIDTH:
        raise AssertionError("Rebuilt F14 has the wrong width")
    if rebuilt_graphic.raw_data != rebuilt_raw_data:
        raise AssertionError("Rebuilt F14 changed the generated pixel data")
    # Both resources are followed by 4-byte alignment filler, so compare the
    # CLUT from the aligned boundary rather than the raw declared size.
    rebuilt_tail_start = rebuilt_graphic.declared_size + (
        -rebuilt_graphic.declared_size % 4
    )
    original_tail_start = graphic.declared_size + (-graphic.declared_size % 4)
    if rebuilt_f14[rebuilt_tail_start:] != original_f14[original_tail_start:]:
        raise AssertionError("Rebuilt F14 changed the CLUT")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rebuilt_f14)

    print(
        f"Static glyphs rendered: {STATIC_GLYPH_COUNT} "
        f"({GLYPHS_PER_PLANE}/plane, {EXPECTED_PIXEL_WIDTH}x{graphic.height})"
    )
    print(
        f"F0014 minimum RLE block: {minimum_main_block_size}/"
        f"{graphic.declared_size} bytes ({rle_margin} bytes free)"
    )
    print(f"F0014 main block: {rebuilt_graphic.declared_size} bytes")
    print(
        f"Preserved F0014 tail: "
        f"{len(original_f14) - graphic.declared_size} bytes"
    )
    print(f"F0014 output: {output_path} ({len(rebuilt_f14)} bytes)")
    return rebuilt_f14


if __name__ == "__main__":
    build_f14()
