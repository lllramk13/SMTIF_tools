from pathlib import Path

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

STATIC_GLYPH_COUNT = 0x0567
GLYPHS_PER_PLANE = 346
PLANE_COUNT = 4
CELL_WIDTH = 12
CELL_HEIGHT = 12
ROWS_PER_COLUMN = 21
EXPECTED_PIXEL_WIDTH = 208
EXPECTED_HEIGHT = 252


def _glyph_pixel_is_ink(glyph, x, y):
    """Return True for an ink pixel in IF's inverted packed 1bpp format."""
    byte_value = glyph[y * 2 + x // 8]
    return not byte_value & (1 << (x % 8))


def build_static_font_pixels(font_data, original_pixels, width, height):
    """Overlay the first 1383 font glyphs into F14's four bit planes."""
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
    rebuilt_pixels = build_static_font_pixels(
        font_data,
        original_pixels,
        graphic.pixel_width,
        graphic.height,
    )
    rebuilt_raw_data = pack_4bpp_pixels(
        rebuilt_pixels,
        graphic.pixel_width,
        graphic.height,
    )
    rebuilt_f14 = rebuild_graphic_resource(
        original_f14,
        rebuilt_raw_data,
    )

    rebuilt_graphic = decompress_graphic_resource(rebuilt_f14)
    if rebuilt_graphic.declared_size != graphic.declared_size:
        raise AssertionError("Rebuilt F14 changed the main resource size")
    if rebuilt_graphic.raw_data != rebuilt_raw_data:
        raise AssertionError("Rebuilt F14 changed the generated pixel data")
    if rebuilt_f14[graphic.declared_size:] != original_f14[graphic.declared_size:]:
        raise AssertionError("Rebuilt F14 changed the CLUT or file padding")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rebuilt_f14)

    print(f"Static glyphs rendered: {STATIC_GLYPH_COUNT}")
    print(f"F0014 main block: {graphic.declared_size} bytes")
    print(
        f"Preserved F0014 tail: "
        f"{len(original_f14) - graphic.declared_size} bytes"
    )
    print(f"F0014 output: {output_path} ({len(rebuilt_f14)} bytes)")
    return rebuilt_f14


if __name__ == "__main__":
    build_f14()
