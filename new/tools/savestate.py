#!/usr/bin/env python3
"""Read main RAM and the CPU registers out of a DuckStation savestate.

A savestate taken while the symptom is on screen is worth more than any RAM
dump: it holds the exact moment, and it can be re-read as many times as a
theory needs.  Both slowdown investigations so far were settled this way --
the ordering table in a state file showed a node linked to itself, which no
amount of watching the game could have shown.

Run from new/:
    python tools/savestate.py <file.sav> --ram out.bin
    python tools/savestate.py <file.sav> --registers
"""
import argparse
import struct
import sys
from compression import zstd
from pathlib import Path

MAGIC = b"DUCC"
COMPRESSED_SIZE = 0xCC
UNCOMPRESSED_SIZE = 0xD0
STREAM_OFFSET = 0xD4

# The register block sits at a fixed offset but is not word-aligned to the
# start of the file, so every read is shifted by two bytes.
REGISTER_OFFSET = 0x3E
REGISTER_NAMES = (
    "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 "
    "s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra hi lo pc"
).split()

RAM_BASE_ADDRESS = 0x80000000
RAM_SIZE = 0x200000
# The state file has no RAM offset field we can trust, so find RAM by a
# landmark inside it: the game's file-position table starts with the LBA and
# size of the first two disc files, and it always lives at this address.
FILEPOS_SIGNATURE = struct.pack("<IIII", 557, 11832, 563, 16756)
FILEPOS_ADDRESS = 0x80107740


def load(path):
    """Return ``(state_bytes, ram_offset)`` for a savestate."""
    raw = Path(path).read_bytes()
    if raw[:4] != MAGIC:
        raise ValueError(f"{path} is not a DuckStation savestate")
    offset = struct.unpack_from("<I", raw, STREAM_OFFSET)[0]
    size = struct.unpack_from("<I", raw, UNCOMPRESSED_SIZE)[0]
    state = zstd.decompress(raw[offset:])
    if len(state) != size:
        raise ValueError(f"expected {size} bytes of state, got {len(state)}")

    landmark = state.find(FILEPOS_SIGNATURE)
    if landmark < 0:
        raise ValueError("could not find the file-position table in the state")
    return state, landmark - (FILEPOS_ADDRESS - RAM_BASE_ADDRESS)


def read_ram(path):
    state, ram_offset = load(path)
    return state[ram_offset:ram_offset + RAM_SIZE]


def read_registers(path):
    state, _ = load(path)
    return {
        name: struct.unpack_from("<I", state, REGISTER_OFFSET + index * 4)[0]
        for index, name in enumerate(REGISTER_NAMES)
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("savestate", type=Path)
    parser.add_argument("--ram", type=Path, help="write main RAM here")
    parser.add_argument("--registers", action="store_true")
    arguments = parser.parse_args()

    if arguments.ram:
        arguments.ram.write_bytes(read_ram(arguments.savestate))
        print(f"wrote {RAM_SIZE} bytes to {arguments.ram}")
    if arguments.registers:
        registers = read_registers(arguments.savestate)
        for index, name in enumerate(REGISTER_NAMES):
            end = "\n" if index % 4 == 3 else "  "
            print(f"{name:>4} {registers[name]:08X}", end=end)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
