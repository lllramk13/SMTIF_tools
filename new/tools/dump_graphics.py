#!/usr/bin/env python3
"""Dump every graphic resource on the disc to PNG so they can be browsed.

The game stores images as ``02 01``-tagged RLE blocks (``src.graphic_resource``).
Most files hold exactly one at offset 0, but containers such as F0007 pack many
back to back, so this scans the whole file for the tag instead of trusting the
header.

Pixels are 4bpp indices into a CLUT that lives elsewhere, so the PNGs come out
as 16-level greyscale.  That is enough to *identify* an image; the real palette
only matters once you are editing one.

Run from new/:  python tools/dump_graphics.py [--out DIR] [--file F0007]
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from src.graphic_resource import GRAPHIC_RLE_TYPE, decompress_graphic_resource

SOURCE_DIRECTORY = NEW_DIR.parent / "extrac" / "D"
DEFAULT_OUTPUT = NEW_DIR / "build" / "graphics"
# A 4bpp block wider than this is almost certainly a false positive on the tag.
MAX_PIXEL_WIDTH = 1024
MAX_HEIGHT = 512


def _to_png(resource, path):
    from PIL import Image
    import numpy as np

    data = np.frombuffer(resource.raw_data, dtype=np.uint8)
    pixels = np.empty(data.size * 2, dtype=np.uint8)
    pixels[0::2] = data & 0x0F
    pixels[1::2] = data >> 4
    width = resource.pixel_width
    height = min(resource.height, pixels.size // width)
    if width <= 0 or height <= 0:
        return False
    image = (pixels[: width * height].reshape(height, width) * 17).astype("uint8")
    Image.fromarray(image).save(path)
    return True


def _blocks(data):
    """Yield (offset, resource) for every decodable graphic block."""
    offset = 0
    while True:
        offset = data.find(GRAPHIC_RLE_TYPE, offset)
        if offset < 0:
            return
        try:
            resource = decompress_graphic_resource(data[offset:])
        except Exception:
            offset += 2
            continue
        if (
            0 < resource.pixel_width <= MAX_PIXEL_WIDTH
            and 0 < resource.height <= MAX_HEIGHT
        ):
            yield offset, resource
            offset += max(resource.declared_size, 2)
        else:
            offset += 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--file",
        action="append",
        help="Only scan these stems (e.g. --file F0007).  Default: all.",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=64,
        help="Stop after this many blocks per file (containers hold hundreds).",
    )
    arguments = parser.parse_args()

    output = Path(arguments.out)
    output.mkdir(parents=True, exist_ok=True)

    sources = sorted(SOURCE_DIRECTORY.iterdir())
    if arguments.file:
        wanted = {name.upper() for name in arguments.file}
        sources = [path for path in sources if path.stem.upper() in wanted]

    total = 0
    for path in sources:
        data = path.read_bytes()
        for index, (offset, resource) in enumerate(_blocks(data)):
            if index >= arguments.max_blocks:
                print(f"{path.stem}: stopped at {arguments.max_blocks} blocks")
                break
            name = (
                f"{path.stem}_{offset:08X}"
                f"_{resource.pixel_width}x{resource.height}.png"
            )
            if _to_png(resource, output / name):
                total += 1
    print(f"{total} graphics -> {output}")


if __name__ == "__main__":
    main()
