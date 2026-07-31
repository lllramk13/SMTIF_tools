"""List PS1 memory-card directory entries and basic save-block metadata."""

import argparse
from pathlib import Path


BLOCK_SIZE = 8192
FRAME_SIZE = 128
DIRECTORY_ENTRY_COUNT = 15


def decode_ascii(data):
    return data.split(b"\0", 1)[0].decode("ascii", errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("card", type=Path)
    arguments = parser.parse_args()

    data = arguments.card.read_bytes()
    if len(data) != 16 * BLOCK_SIZE:
        raise ValueError(
            f"Expected a 128 KiB raw PS1 card, got {len(data)} bytes"
        )
    if data[:2] != b"MC":
        raise ValueError("Missing raw PS1 memory-card MC header")

    print(f"Card: {arguments.card}")
    for slot in range(1, DIRECTORY_ENTRY_COUNT + 1):
        offset = slot * FRAME_SIZE
        entry = data[offset:offset + FRAME_SIZE]
        state = entry[0]
        if state & 0xF0 != 0x50:
            continue
        size = int.from_bytes(entry[4:8], "little")
        next_block = int.from_bytes(entry[8:10], "little")
        filename = decode_ascii(entry[0x0A:0x1E])
        block = data[slot * BLOCK_SIZE:(slot + 1) * BLOCK_SIZE]
        magic = block[:2]
        icon_flags = block[2]
        block_count = block[3]
        title_bytes = block[4:0x44]
        try:
            title = title_bytes.split(b"\0", 1)[0].decode(
                "shift_jis",
                errors="replace",
            )
        except LookupError:
            title = repr(title_bytes)
        print(
            f"slot={slot:2d} state={state:#04x} size={size:6d} "
            f"next={next_block:#06x} file={filename!r}"
        )
        print(
            f"  block magic={magic!r} icon={icon_flags:#04x} "
            f"blocks={block_count} title={title!r}"
        )


if __name__ == "__main__":
    main()
