"""Build test77 by narrowing test74's MARKER type-6 stride correction.

test64 and later enlarged every type-6 descriptor whose row stride was below
0x100.  EQUIP also owns valid type-6 descriptors and was corrupted by that
over-broad condition.  The failing MARKER descriptor is known from the RAM
dump: its stride is exactly 0xD0.  Change only the comparison and branch so
0xD0 becomes 0x100 while every other type-6 stride is left untouched.
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
    / "SMT_IF_CN_test74_font_rollback_keep_missing_text.bin"
)
OUTPUT_IMAGE = (
    PROJECT
    / "Game"
    / "modified"
    / "SMT_IF_CN_test77_marker_exact_stride_fix.bin"
)
OUTPUT_CUE = OUTPUT_IMAGE.with_suffix(".cue")
MANIFEST = PROJECT / "extrac" / "_iso_manifest.json"

SLPM_PATH = "SLPM_871.54"
LOAD_ADDRESS = 0x8000F800
PATCHES = {
    # sltiu t1,t0,0x100 -> addiu t1,t0,-0xD0
    0x8005C2AC: (bytes.fromhex("0001092D"), bytes.fromhex("30FF0925")),
    # beq t1,zero,done -> bne t1,zero,done
    0x8005C2B0: (bytes.fromhex("03002011"), bytes.fromhex("03002015")),
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
            f"Refusing to overwrite existing test output: {OUTPUT_IMAGE}"
        )

    entry = load_manifest_entry(MANIFEST, SLPM_PATH)
    with SOURCE_IMAGE.open("rb") as image:
        original_slpm = extract_file_from_image(image, entry)
    patched_slpm = bytearray(original_slpm)

    for address, (expected, replacement) in PATCHES.items():
        offset = address - LOAD_ADDRESS
        actual = bytes(patched_slpm[offset:offset + len(expected)])
        if actual != expected:
            raise AssertionError(
                f"Unexpected test74 opcode at {address:#010x}: "
                f"{actual.hex()}, expected {expected.hex()}"
            )
        patched_slpm[offset:offset + len(replacement)] = replacement

    changed_offsets = [
        index
        for index, (before, after) in enumerate(
            zip(original_slpm, patched_slpm)
        )
        if before != after
    ]
    expected_changed_offsets = {
        address - LOAD_ADDRESS + byte_index
        for address, (before, after) in PATCHES.items()
        for byte_index, (old_byte, new_byte) in enumerate(zip(before, after))
        if old_byte != new_byte
    }
    if set(changed_offsets) != expected_changed_offsets:
        raise AssertionError(
            "Unexpected SLPM byte differences: "
            f"{changed_offsets} != {sorted(expected_changed_offsets)}"
        )

    shutil.copyfile(SOURCE_IMAGE, OUTPUT_IMAGE)
    replace_files_in_image(
        OUTPUT_IMAGE,
        MANIFEST,
        {SLPM_PATH: bytes(patched_slpm)},
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
    if verified != bytes(patched_slpm):
        raise AssertionError("Injected SLPM failed full-file verification")

    print(f"Source: {SOURCE_IMAGE}")
    print(f"Image: {OUTPUT_IMAGE}")
    print(f"CUE: {OUTPUT_CUE}")
    print(f"SHA-256: {sha256_file(OUTPUT_IMAGE)}")
    print(f"SLPM changed bytes: {len(changed_offsets)}")
    for address, (before, after) in PATCHES.items():
        print(f"{address:#010x}: {before.hex()} -> {after.hex()}")


if __name__ == "__main__":
    main()
