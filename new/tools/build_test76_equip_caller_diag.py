"""Build a test62-based EQUIP caller diagnostic image.

test62 safely exits the small-font renderer after detecting an invalid string
pointer.  Its diagnostic read targets ``$zero`` though, which DuckStation's
JIT can discard because the loaded value is architecturally unobservable.
Retarget that one load to ``$t0`` so the encoded 0x78xxxxxx address must pass
through the unknown-read handler and appear in the emulator log.
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
    / "SMT_IF_CN_test62_encoded_caller_guard.bin"
)
OUTPUT_IMAGE = (
    PROJECT
    / "Game"
    / "modified"
    / "SMT_IF_CN_test76_equip_caller_diag.bin"
)
OUTPUT_CUE = OUTPUT_IMAGE.with_suffix(".cue")
MANIFEST = PROJECT / "extrac" / "_iso_manifest.json"

SLPM_PATH = "SLPM_871.54"
LOAD_ADDRESS = 0x8000F800
DIAGNOSTIC_ADDRESS = 0x8005C2C4
EXPECTED_LW_ZERO = bytes.fromhex("0000008D")
FORCED_LW_T0 = bytes.fromhex("0000088D")


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
            f"Refusing to overwrite existing diagnostic output: {OUTPUT_IMAGE}"
        )

    entry = load_manifest_entry(MANIFEST, SLPM_PATH)
    with SOURCE_IMAGE.open("rb") as image:
        slpm = bytearray(extract_file_from_image(image, entry))

    offset = DIAGNOSTIC_ADDRESS - LOAD_ADDRESS
    actual = bytes(slpm[offset:offset + 4])
    if actual != EXPECTED_LW_ZERO:
        raise AssertionError(
            f"Unexpected test62 opcode at {DIAGNOSTIC_ADDRESS:#010x}: "
            f"{actual.hex()}, expected {EXPECTED_LW_ZERO.hex()}"
        )
    slpm[offset:offset + 4] = FORCED_LW_T0

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
    if verified[offset:offset + 4] != FORCED_LW_T0:
        raise AssertionError("Injected diagnostic opcode failed verification")

    print(f"Image: {OUTPUT_IMAGE}")
    print(f"CUE: {OUTPUT_CUE}")
    print(f"SHA-256: {sha256_file(OUTPUT_IMAGE)}")
    print(
        f"{DIAGNOSTIC_ADDRESS:#010x}: "
        f"{EXPECTED_LW_ZERO.hex()} -> {FORCED_LW_T0.hex()}"
    )


if __name__ == "__main__":
    main()
