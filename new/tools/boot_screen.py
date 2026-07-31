#!/usr/bin/env python3
"""Export / re-import the full-screen 8bpp boot images.

The boot logo screens are ``02 01`` RLE graphics whose header declares
``width_words`` in 16-bit VRAM words.  The generic reader in
``src.graphic_resource`` assumes 4bpp (``pixel_width = width_words * 4``);
these are 8bpp, so the real width is ``width_words * 2``.

Known screens (SLPM-87154).  The same engine and format are used by the other
Atlus PS1 titles, so the table is just a starting point -- use
``tools/locate_vram_source.py`` to find the equivalents elsewhere.

    F0093  R&D logo ("Research and Development 1")
    F0083  disclaimer, 「このゲームは フィクションであり ...」

Their palettes are *not* a linear ramp: index 255 is black and index 0 is
near-white.  The exact CLUT lives outside the file, so ``export`` renders a
greyscale proof using the ink ramp measured from the original (background at
``--bg``, solid ink at ``--ink``) and ``import`` maps artwork back through the
same ramp.  Round-tripping an unedited PNG reproduces the original indices.

    python tools/boot_screen.py export F0083 --out work/F0083.png
    # ... edit work/F0083.png (black background, white text) ...
    python tools/boot_screen.py import F0083 --png work/F0083.png
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
# Ink ramp measured on the originals: the background index and the darkest ink
# index actually present.  Covering the full observed range is what makes the
# round-trip exact -- clipping at a higher ink point quantises the few deepest
# antialias pixels.
SCREENS = {
    "F0083": {"bg": 31, "ink": 1},
    "F0093": {"bg": 255, "ink": 0},
}


def _align4(value):
    return (value + 3) & ~3


def _load(stem):
    path = SOURCE_DIRECTORY / f"{stem}.BIN"
    resource = decompress_graphic_resource(path.read_bytes())
    width = resource.pixel_width // 2  # 8bpp, not the 4bpp the reader assumes
    return path, resource, width


def _export(arguments):
    from PIL import Image
    import numpy as np

    _, resource, width = _load(arguments.stem)
    indices = np.frombuffer(resource.raw_data, dtype=np.uint8).reshape(
        resource.height, width
    )
    background = arguments.bg
    ink = arguments.ink
    # index -> ink coverage -> greyscale proof (white ink on black)
    coverage = (background - indices.astype(np.int16)) / float(background - ink)
    grey = (np.clip(coverage, 0, 1) * 255).astype(np.uint8)
    output = Path(arguments.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(grey).save(output)
    print(f"{arguments.stem}: {width}x{resource.height} 8bpp -> {output}")


def _import(arguments):
    from PIL import Image, ImageChops
    import numpy as np

    path, resource, width = _load(arguments.stem)
    original = path.read_bytes()
    image = Image.open(arguments.png).convert("L")
    if image.size != (width, resource.height):
        raise SystemExit(
            f"{arguments.stem}: PNG must be {width}x{resource.height}, "
            f"got {image.width}x{image.height}"
        )

    if not 0 < arguments.scale_content <= 1:
        raise SystemExit("--scale-content must be greater than 0 and at most 1")
    if arguments.levels is not None and arguments.levels < 2:
        raise SystemExit("--levels must be at least 2")

    if arguments.scale_content != 1:
        content_box = ImageChops.difference(
            image,
            Image.new("L", image.size, 0),
        ).getbbox()
        if content_box:
            content = image.crop(content_box)
            resized_size = (
                round(content.width * arguments.scale_content),
                round(content.height * arguments.scale_content),
            )
            content = content.resize(resized_size, Image.Resampling.LANCZOS)
            fitted = Image.new("L", image.size, 0)
            fitted.paste(
                content,
                (
                    (image.width - resized_size[0]) // 2,
                    (image.height - resized_size[1]) // 2,
                ),
            )
            image = fitted

    background = arguments.bg
    ink = arguments.ink
    coverage = np.asarray(image, dtype=np.float32) / 255.0
    if arguments.levels is not None:
        steps = arguments.levels - 1
        coverage = np.rint(coverage * steps) / steps

    if arguments.processed_preview:
        preview = Path(arguments.processed_preview)
        preview.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.rint(coverage * 255).astype(np.uint8)).save(preview)
        print(f"Processed preview: {preview}")

    indices = np.rint(
        background - coverage * (background - ink)
    ).astype(np.uint8)

    # compress_rle returns a complete 0x01/0x01 resource; the graphic block
    # stores the bare RLE stream, so drop its 12-byte resource header.
    body = compress_rle(indices.tobytes())[12:]
    declared = GRAPHIC_HEADER_SIZE + len(body)

    # The file holds a *second* block after the image: a 256x1 CLUT.  Blocks
    # are 4-byte aligned, so re-encoding to a different size has to carry the
    # palette along -- leaving it at the original offset silently breaks the
    # colours of every screen whose artwork compresses differently.
    original_tail_at = _align4(resource.declared_size)
    tail = original[original_tail_at:]
    if len(tail) >= 8:
        tail_declared = int.from_bytes(tail[4:8], "little")
        if 16 <= tail_declared <= len(tail):
            meaningful_tail = _align4(tail_declared)
            trailing_padding = tail[meaningful_tail:]
            # F0083/F0093 contain a declared 528-byte CLUT followed only by
            # sector padding.  Moving that zero padding with the CLUT wastes
            # hundreds of bytes of image capacity.
            if not any(trailing_padding):
                tail = tail[:meaningful_tail]
    end = _align4(declared) + len(tail)
    if end > len(original):
        raise SystemExit(
            f"{arguments.stem}: image + palette need {end} bytes, but the disc "
            f"slot is only {len(original)}.  Simplify the artwork "
            "(flat background, fewer gradients)."
        )
    rebuilt = bytearray(len(original))
    rebuilt[:GRAPHIC_HEADER_SIZE] = original[:GRAPHIC_HEADER_SIZE]
    rebuilt[4:8] = declared.to_bytes(4, "little")
    rebuilt[GRAPHIC_HEADER_SIZE:declared] = body
    rebuilt[_align4(declared):end] = tail

    if arguments.dest_from:
        # Bytes 8..12 of each block are its VRAM destination, and the boot
        # display routine's sprite/CLUT coordinates are hardcoded for
        # F0093's layout (image at 320,0 and palette at 0,480).  A screen
        # authored for a different path -- F0083 targets 0,0 for *both*, so
        # its palette lands on top of its own first row -- has to be
        # retargeted or it draws half-width in the wrong colours.
        model = (SOURCE_DIRECTORY / f"{arguments.dest_from}.BIN").read_bytes()
        model_clut = _align4(int.from_bytes(model[4:8], "little"))
        rebuilt[8:12] = model[8:12]
        clut_at = _align4(declared)
        rebuilt[clut_at + 8:clut_at + 12] = model[model_clut + 8:model_clut + 12]

    rebuilt = bytes(rebuilt)

    check = decompress_graphic_resource(rebuilt)
    if check.raw_data != indices.tobytes():
        raise SystemExit(f"{arguments.stem}: re-encode did not round-trip")

    output = Path(arguments.out or (NEW_DIR / "data" / "boot_screens" / f"{arguments.stem}.BIN"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rebuilt)
    slack = len(original) - end
    print(
        f"{arguments.stem}: {end} bytes used of {len(original)} "
        f"({slack} spare) -> {output}"
    )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("export", "import"):
        part = sub.add_parser(name)
        part.add_argument("stem", choices=sorted(SCREENS))
        part.add_argument("--bg", type=int)
        part.add_argument("--ink", type=int)
        if name == "export":
            part.add_argument("--out", required=True)
        else:
            part.add_argument("--png", required=True)
            part.add_argument("--out")
            part.add_argument(
                "--levels",
                type=int,
                help="quantise antialiasing to this many greyscale levels",
            )
            part.add_argument(
                "--scale-content",
                type=float,
                default=1.0,
                help=(
                    "scale the non-black artwork around the canvas centre "
                    "without changing the 320x240 canvas"
                ),
            )
            part.add_argument(
                "--processed-preview",
                help="write the fitted/quantised greyscale artwork here",
            )
            part.add_argument(
                "--dest-from",
                help=(
                    "copy both blocks' VRAM destinations from this screen "
                    "(use F0093 for anything shown by the boot sequence)"
                ),
            )
    arguments = parser.parse_args()
    defaults = SCREENS[arguments.stem]
    if arguments.bg is None:
        arguments.bg = defaults["bg"]
    if arguments.ink is None:
        arguments.ink = defaults["ink"]
    (_export if arguments.action == "export" else _import)(arguments)


if __name__ == "__main__":
    main()
