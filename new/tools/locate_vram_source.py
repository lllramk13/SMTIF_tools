#!/usr/bin/env python3
"""Find which disc file produced what is currently on screen.

Take a VRAM dump at the screen you care about, point this at the disc image,
and it reports the file (or raw LBA) each on-screen texture came from.  It
needs no knowledge of the game's formats, so it works on any PS1 title -- the
other Atlus discs included.

Why it works through compression
--------------------------------
These games store graphics RLE-compressed, so most of a texture is *not* on
the disc verbatim.  But RLE only wins on runs of identical bytes: a
high-entropy stretch -- dithered gradients, antialiased text, photographic
detail -- is emitted as a literal block, byte for byte.  So the tool ranks
candidate sample windows by how *unrepetitive* they are and searches those.
Flat areas are skipped precisely because they are the ones that compress.

That is why a single 48-byte sample through the "Research and Development"
lettering located F0093.BIN immediately, while samples through the flat
background matched nothing.

Usage
-----
    python tools/locate_vram_source.py --vram ram_vram/rndvram.bin \
        --disc "Game/ogd/SLPM-87154.bin"

    # limit to a rectangle you already identified, in 16bpp VRAM pixels
    python tools/locate_vram_source.py ... --region 360,45,72,150
"""
import argparse
import json
from pathlib import Path

VRAM_WIDTH = 1024
VRAM_HEIGHT = 512
SAMPLE_BYTES = 48


def _samples(vram, region, count):
    """Rank sample windows by byte diversity and return the most distinctive."""
    import numpy as np

    picture = np.frombuffer(vram, dtype=np.uint16).reshape(VRAM_HEIGHT, VRAM_WIDTH)
    if region:
        x, y, width, height = region
        picture = picture[y : y + height, x : x + width]
        origin = (x, y)
    else:
        origin = (0, 0)

    half = SAMPLE_BYTES // 2
    scored = []
    for row in range(0, picture.shape[0], 2):
        line = picture[row]
        for column in range(0, line.size - half, half):
            window = line[column : column + half].tobytes()
            if len(window) < SAMPLE_BYTES:
                continue
            # Distinct-byte count is a cheap, robust stand-in for entropy, and
            # it is exactly what predicts "RLE stored this literally".
            diversity = len(set(window))
            if diversity < SAMPLE_BYTES // 2:
                continue
            scored.append((diversity, origin[0] + column, origin[1] + row, window))
    scored.sort(key=lambda item: -item[0])

    chosen, seen_rows = [], set()
    for diversity, x, y, window in scored:
        # Spread the samples out; twenty hits on one glyph teach us nothing.
        if y // 16 in seen_rows:
            continue
        seen_rows.add(y // 16)
        chosen.append((x, y, window))
        if len(chosen) >= count:
            break
    return chosen


def _load_manifest(path):
    if path is None or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _locate(manifest, offset):
    """Map a raw disc byte offset to (file, offset-in-file) when possible."""
    if manifest is None:
        return None
    raw = manifest["raw_sector_size"]
    user_offset = manifest["form1_user_offset"]
    user_size = manifest["form1_user_size"]
    lba, remainder = divmod(offset, raw)
    for entry in manifest["entries"]:
        path = entry.get("path")
        if not path:
            continue
        sectors = (entry["size"] + user_size - 1) // user_size
        if entry["extent_lba"] <= lba < entry["extent_lba"] + sectors:
            inside = (lba - entry["extent_lba"]) * user_size + remainder - user_offset
            return path, inside
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vram", required=True, help="1 MB VRAM dump")
    parser.add_argument("--disc", required=True, help="raw 2352-byte-sector image")
    parser.add_argument("--manifest", default=None, help="_iso_manifest.json, optional")
    parser.add_argument(
        "--region",
        default=None,
        help="x,y,w,h in 16bpp VRAM pixels; default is the whole dump",
    )
    parser.add_argument("--samples", type=int, default=24)
    arguments = parser.parse_args()

    region = None
    if arguments.region:
        region = tuple(int(part) for part in arguments.region.split(","))
        if len(region) != 4:
            raise SystemExit("--region needs x,y,w,h")

    vram = Path(arguments.vram).read_bytes()
    disc = Path(arguments.disc).read_bytes()
    manifest = _load_manifest(arguments.manifest)

    found = {}
    misses = 0
    for x, y, window in _samples(vram, region, arguments.samples):
        offset = disc.find(window)
        if offset < 0:
            misses += 1
            continue
        placed = _locate(manifest, offset)
        key = placed[0] if placed else f"LBA {offset // 2352}"
        found.setdefault(key, []).append((x, y, offset, placed[1] if placed else None))

    if not found:
        print(f"No matches ({misses} samples searched).")
        print("The data may be LZ77-packed rather than RLE, or built at runtime.")
        return

    for key, hits in sorted(found.items(), key=lambda item: -len(item[1])):
        print(f"{key}  ({len(hits)} hits)")
        for x, y, offset, inside in hits[:4]:
            where = f"+0x{inside:X}" if inside is not None else ""
            print(f"    VRAM ({x:4d},{y:3d})  disc 0x{offset:08X} {where}")
    print(f"\n{misses} of {misses + sum(len(v) for v in found.values())} samples unmatched")


if __name__ == "__main__":
    main()
