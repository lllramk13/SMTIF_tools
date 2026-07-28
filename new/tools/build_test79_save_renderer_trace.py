"""Trace which direct F14 call draws SAVE/LOAD reserved-code strings.

Each candidate call is redirected through a temporary logger.  It emits two
intentional unknown reads before tail-calling the original F14 renderer:

* 0x780xxxxx encodes the candidate call's return address.
* 0x7900xxxx encodes the first 16-bit glyph code at ``a0``.

The logger borrows the MARKER stride-helper cave, so the common constructor
hook is restored to its original two instructions in this diagnostic image.
Do not use test79 to test MARKER.
"""

import hashlib
import shutil
from pathlib import Path

from src.disc_injector import (
    extract_file_from_image,
    load_manifest_entry,
    replace_files_in_image,
)


PROJECT = Path(__file__).resolve().parents[2]
SOURCE_IMAGE = (
    PROJECT
    / "Game"
    / "modified"
    / "SMT_IF_CN_test78_save_name_hybrid_fix.bin"
)
OUTPUT_IMAGE = (
    PROJECT
    / "Game"
    / "modified"
    / "SMT_IF_CN_test79_save_renderer_trace.bin"
)
OUTPUT_CUE = OUTPUT_IMAGE.with_suffix(".cue")
MANIFEST = PROJECT / "extrac" / "_iso_manifest.json"

SLPM_PATH = "SLPM_871.54"
LOAD_ADDRESS = 0x8000F800

PATCHES = {
    # Temporarily restore the constructor words whose helper cave is borrowed.
    0x8006F0A8: (
        bytes.fromhex("A6700108"),
        bytes.fromhex("00141E00"),  # sll v0,fp,16
    ),
    0x8006F0AC: (
        bytes.fromhex("00141E00"),
        bytes.fromhex("03140200"),  # sra v0,v0,16
    ),
    # Direct F14 candidates -> jal trace logger at 0x8005C298.
    0x80072C34: (bytes.fromhex("7F1D010C"), bytes.fromhex("A670010C")),
    0x80074F70: (bytes.fromhex("5B2B010C"), bytes.fromhex("A670010C")),
    0x800B85C8: (bytes.fromhex("7F1D010C"), bytes.fromhex("A670010C")),
    # Temporary logger, followed by two harmless padding words.
    0x8005C298: (
        bytes.fromhex(
            "03140200"
            "FAFF4824"
            "07000015"
            "00000000"
            "0008288E"
            "30FF0925"
            "03002015"
            "00000000"
            "00010834"
            "000828AE"
            "2CBC0108"
            "00000000"
        ),
        bytes.fromhex(
            "0078083C"  # lui t0,0x7800
            "FFFFE933"  # andi t1,ra,0xFFFF
            "25400901"  # or t0,t0,t1
            "0000088D"  # lw t0,0(t0): log caller
            "00008994"  # lhu t1,0(a0)
            "0079083C"  # lui t0,0x7900
            "25400901"  # or t0,t0,t1
            "0000088D"  # lw t0,0(t0): log first glyph
            "7F1D0108"  # j 0x800475FC
            "00000000"  # nop
            "00000000"  # padding
            "00000000"  # padding
        ),
    ),
}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main():
    if not SOURCE_IMAGE.is_file():
        raise FileNotFoundError(SOURCE_IMAGE)
    if OUTPUT_IMAGE.exists() or OUTPUT_CUE.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing diagnostic: {OUTPUT_IMAGE}"
        )

    entry = load_manifest_entry(MANIFEST, SLPM_PATH)
    with SOURCE_IMAGE.open("rb") as image:
        slpm = bytearray(extract_file_from_image(image, entry))

    for address, (expected, replacement) in PATCHES.items():
        offset = address - LOAD_ADDRESS
        actual = bytes(slpm[offset:offset + len(expected)])
        if actual != expected:
            raise AssertionError(
                f"Unexpected opcode/data at {address:#010x}: "
                f"{actual.hex()}, expected {expected.hex()}"
            )
        if len(expected) != len(replacement):
            raise AssertionError(f"Patch size changed at {address:#010x}")
        slpm[offset:offset + len(replacement)] = replacement

    shutil.copyfile(SOURCE_IMAGE, OUTPUT_IMAGE)
    replace_files_in_image(
        OUTPUT_IMAGE,
        MANIFEST,
        {SLPM_PATH: bytes(slpm)},
    )
    OUTPUT_CUE.write_text(
        f'FILE "{OUTPUT_IMAGE.name}" BINARY\n'
        "  TRACK 01 MODE2/2352\n"
        "    INDEX 01 00:00:00\n",
        encoding="ascii",
        newline="\n",
    )

    with OUTPUT_IMAGE.open("rb") as image:
        verified = extract_file_from_image(image, entry)
    if verified != bytes(slpm):
        raise AssertionError("Injected diagnostic SLPM failed verification")

    print(f"Image: {OUTPUT_IMAGE}")
    print(f"CUE: {OUTPUT_CUE}")
    print(f"SHA-256: {sha256_file(OUTPUT_IMAGE)}")
    print("Trace pairs: 0x780xxxxx caller, then 0x7900xxxx first glyph")
    print("Expected caller IDs: 072C3C, 074F78, 0B85D0")


if __name__ == "__main__":
    main()
