#!/usr/bin/env python3
"""Build an F0093-compatible 256-colour RLE boot-screen payload.

The inserted page deliberately reuses the original R&D screen's geometry,
texture pages, VRAM destination and 256-entry CLUT layout.  The payload is
always padded to the seven-sector safe limit; the MIPS hook reads it once,
decodes the RLE image into the original R&D texture, uploads the CLUT, and only
then enters the existing fade/hold/draw loop.
"""
import argparse
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
PROJECT_DIRECTORY = NEW_DIRECTORY.parent
sys.path.insert(0, str(NEW_DIRECTORY))

from src.compression import compress_rle


SOURCE_F0093 = PROJECT_DIRECTORY / "extrac" / "D" / "F0093.BIN"
OUTPUT = NEW_DIRECTORY / "data" / "boot_screens" / "BOOT_BLOB.BIN"
PREVIEW = NEW_DIRECTORY / "build" / "boot_watermark_preview.png"

WIDTH = 320
HEIGHT = 240
COLOR_COUNT = 256
GRAPHIC_HEADER_SIZE = 16
CLUT_BLOCK_SIZE = 16 + COLOR_COUNT * 2
SECTOR_SIZE = 2048
PAYLOAD_SECTORS = 7
PAYLOAD_SIZE = PAYLOAD_SECTORS * SECTOR_SIZE

# Minimal 5x7 font used for the self-contained default artwork.
FONT = {
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
}


def align4(value):
    return (value + 3) & ~3


def require_pillow():
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Pillow is required to build the boot watermark") from error
    return Image


def render_text(text, scale=2):
    Image = require_pillow()
    text = text.upper()
    unsupported = sorted(set(text) - set(FONT))
    if unsupported:
        raise ValueError(f"Unsupported built-in watermark characters: {unsupported}")

    glyph_width = 6 * scale
    artwork_width = max(0, len(text) * glyph_width - scale)
    artwork_height = 7 * scale
    if artwork_width > WIDTH or artwork_height > HEIGHT:
        raise ValueError(
            f"Watermark text needs {artwork_width}x{artwork_height}, "
            f"limit is {WIDTH}x{HEIGHT}"
        )

    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    pixels = image.load()
    origin_x = (WIDTH - artwork_width) // 2
    origin_y = (HEIGHT - artwork_height) // 2
    for character_number, character in enumerate(text):
        for source_y, row_bits in enumerate(FONT[character]):
            for source_x in range(5):
                if not (row_bits & (1 << (4 - source_x))):
                    continue
                x = origin_x + character_number * glyph_width + source_x * scale
                y = origin_y + source_y * scale
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[x + dx, y + dy] = (255, 255, 255)
    return image


def load_png(path):
    Image = require_pillow()
    source = Image.open(path).convert("RGBA")
    if source.size != (WIDTH, HEIGHT):
        raise ValueError(
            f"Watermark PNG must be {WIDTH}x{HEIGHT}, got "
            f"{source.width}x{source.height}"
        )
    background = Image.new("RGBA", source.size, (0, 0, 0, 255))
    return Image.alpha_composite(background, source).convert("RGB")


def quantize_image(image):
    Image = require_pillow()
    method = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT")
    dither = getattr(getattr(Image, "Dither", Image), "NONE")
    return image.quantize(colors=COLOR_COUNT, method=method, dither=dither)


def flattened_indices(quantized):
    getter = getattr(quantized, "get_flattened_data", None)
    return bytes(getter() if getter else quantized.getdata())


def ps1_palette(quantized):
    rgb_palette = quantized.getpalette()[:COLOR_COUNT * 3]
    rebuilt = bytearray(COLOR_COUNT * 2)
    for index in range(COLOR_COUNT):
        red, green, blue = rgb_palette[index * 3:index * 3 + 3]
        colour = (red >> 3) | ((green >> 3) << 5) | ((blue >> 3) << 10)
        # Match F0093: transparent RGB zero is represented as opaque black.
        if colour == 0:
            colour = 0x8000
        rebuilt[index * 2:index * 2 + 2] = colour.to_bytes(2, "little")
    return bytes(rebuilt)


def build_payload(indices, palette):
    model = SOURCE_F0093.read_bytes()
    model_declared = int.from_bytes(model[4:8], "little")
    model_clut_at = align4(model_declared)
    clut_block = bytearray(
        model[model_clut_at:model_clut_at + CLUT_BLOCK_SIZE]
    )
    if (
        clut_block[:2] != b"\x02\x00"
        or int.from_bytes(clut_block[4:8], "little") != CLUT_BLOCK_SIZE
    ):
        raise ValueError("F0093 CLUT block layout is not the expected 256x1 block")

    rle_body = compress_rle(indices)[12:]
    declared = GRAPHIC_HEADER_SIZE + len(rle_body)
    clut_at = align4(declared)
    used_size = clut_at + CLUT_BLOCK_SIZE
    if used_size > PAYLOAD_SIZE:
        raise ValueError(
            f"F0093-compatible watermark needs {used_size} bytes, beyond the "
            f"safe {PAYLOAD_SIZE}-byte/seven-sector buffer. Simplify the image."
        )

    rebuilt = bytearray(PAYLOAD_SIZE)
    rebuilt[:GRAPHIC_HEADER_SIZE] = model[:GRAPHIC_HEADER_SIZE]
    rebuilt[4:8] = declared.to_bytes(4, "little")
    # Reuse the R&D image destination exactly: VRAM word (320,0), 160x240.
    rebuilt[8:16] = model[8:16]
    rebuilt[GRAPHIC_HEADER_SIZE:declared] = rle_body
    rebuilt[clut_at:clut_at + CLUT_BLOCK_SIZE] = clut_block
    rebuilt[
        clut_at + GRAPHIC_HEADER_SIZE:clut_at + CLUT_BLOCK_SIZE
    ] = palette
    return bytes(rebuilt), declared, used_size


def write_preview(path, quantized):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    quantized.convert("RGB").save(path)


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--png", type=Path)
    source.add_argument("--text", default="SMT IF CHINESE")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--preview", type=Path, default=PREVIEW)
    arguments = parser.parse_args()

    image = (
        load_png(arguments.png)
        if arguments.png
        else render_text(arguments.text)
    )
    quantized = quantize_image(image)
    indices = flattened_indices(quantized)
    palette = ps1_palette(quantized)
    payload, declared, used_size = build_payload(indices, palette)

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_bytes(payload)
    write_preview(arguments.preview, quantized)

    print(
        f"Boot watermark: {WIDTH}x{HEIGHT} 8bpp, {COLOR_COUNT}-entry CLUT, "
        f"F0093 RLE block {declared} bytes"
    )
    print(
        f"Resource uses {used_size} of {PAYLOAD_SIZE} bytes "
        f"({PAYLOAD_SECTORS} raw sectors)"
    )
    print(f"Raw payload: {arguments.out}")
    print(f"Preview: {arguments.preview}")


if __name__ == "__main__":
    main()
