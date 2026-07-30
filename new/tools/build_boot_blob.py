#!/usr/bin/env python3
"""Pack the two boot-screen images into one block the routine reads in a single go.

The boot display routine cannot seek twice.  Its read path (0x800291DC ->
0x80029144) records CD state 12, and the Complete handler's state-12 branch was
only ever built to run once: a second read to a *different* LBA never delivers,
retries run out, and the boot hangs on its next load.  Reading the same LBA
twice is fine, because that needs no seek at all.

So do not read twice.  Widen the single read to seven sectors -- the most its
destination can take -- and put both images in it at different VRAM
destinations, then draw each one by pointing the sprites at a different texture
page.

Layout of the 14,336-byte blob:

    F0093 image block   -> VRAM word (320, 0)     unchanged, the R&D logo
    F0093 CLUT block    -> VRAM word (0, 480)     unchanged
    our image block     -> VRAM word (320, 256)   directly below the first
    zero padding

There is deliberately no second palette: the extra page is encoded against
F0093's own CLUT (index 255 black, index 0 near-white), so the sprite's palette
selection never has to change either.

    python tools/build_boot_blob.py --png ../work/boot/PLACEHOLDER.png
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from src.compression import compress_rle
from src.graphic_resource import (
    GRAPHIC_HEADER_SIZE,
    decompress_graphic_resource,
)

SOURCE_DIRECTORY = NEW_DIR.parent / "extrac" / "D"
DEFAULT_OUTPUT = NEW_DIR / "data" / "boot_screens" / "BOOT_BLOB.BIN"
# The sector destination is 0x801DF000 and the next structure starts at
# 0x801E2800, so a read can bring in at most 0x3800 bytes -- seven sectors.
# Ten overruns both 0x801E2800 and 0x801E4000, which are CD driver state, and
# the boot dies on its next load.
BLOB_SECTORS = 7
BLOB_SIZE = BLOB_SECTORS * 2048
# F0093's palette runs dark-to-light in reverse: index 255 is black, 0 near-white.
BACKGROUND_INDEX = 255
INK_INDEX = 0
# Second image lands one screen below the first, so the sprites only need a
# different texture page (0x10 | 5 and 0x10 | 7 instead of 5 and 7).
EXTRA_VRAM_X = 320
EXTRA_VRAM_Y = 256


def _align4(value):
    return (value + 3) & ~3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--png", required=True, help="320x240 greyscale artwork")
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--levels",
        type=int,
        default=2,
        help=(
            "ink levels to quantise the artwork to.  The budget left after the "
            "logo and its palette is about 4,880 bytes, and antialiasing is "
            "what costs RLE the most: 2 levels fits, 4 already does not."
        ),
    )
    arguments = parser.parse_args()

    from PIL import Image
    import numpy as np

    source = (SOURCE_DIRECTORY / "F0093.BIN").read_bytes()
    logo = decompress_graphic_resource(source)
    width = logo.pixel_width // 2  # 8bpp, not the 4bpp the reader assumes
    clut_at = _align4(logo.declared_size)
    clut_block = source[clut_at:clut_at + 528]
    if clut_block[:2] != b"\x02\x00":
        raise SystemExit("F0093's palette block is not where it was expected")

    image = Image.open(arguments.png).convert("L")
    if image.size != (width, logo.height):
        raise SystemExit(
            f"artwork must be {width}x{logo.height}, got "
            f"{image.width}x{image.height}"
        )
    coverage = np.asarray(image, dtype=np.float32) / 255.0
    if arguments.levels > 1:
        steps = arguments.levels - 1
        coverage = np.rint(coverage * steps) / steps
    indices = np.rint(
        BACKGROUND_INDEX - coverage * (BACKGROUND_INDEX - INK_INDEX)
    ).astype(np.uint8)

    body = compress_rle(indices.tobytes())[12:]
    extra = bytearray(GRAPHIC_HEADER_SIZE)
    extra[0:2] = source[0:2]                                   # same block type
    extra[4:8] = (GRAPHIC_HEADER_SIZE + len(body)).to_bytes(4, "little")
    extra[8:10] = EXTRA_VRAM_X.to_bytes(2, "little")
    extra[10:12] = EXTRA_VRAM_Y.to_bytes(2, "little")
    extra[12:14] = source[12:14]                               # width in words
    extra[14:16] = source[14:16]                               # height
    extra += body

    blob = bytearray(BLOB_SIZE)
    cursor = 0
    for name, block in (
        ("R&D image", source[:logo.declared_size]),
        ("R&D palette", clut_block),
        ("extra image", bytes(extra)),
    ):
        cursor = _align4(cursor)
        if cursor + len(block) > BLOB_SIZE:
            raise SystemExit(
                f"{name} does not fit: needs {cursor + len(block)} of {BLOB_SIZE}"
            )
        blob[cursor:cursor + len(block)] = block
        print(f"  {name:12} at {cursor:6} .. {cursor + len(block):6}")
        cursor += len(block)

    output = Path(arguments.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bytes(blob))
    print(f"{cursor} of {BLOB_SIZE} bytes used -> {output}")


if __name__ == "__main__":
    main()
