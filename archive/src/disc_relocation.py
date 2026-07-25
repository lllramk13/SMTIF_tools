"""Move an oversized file into the disc's free tail sectors.

Normal injection replaces files byte-for-byte in place (see ``disc_injector``);
keeping every file at its original offset and size is what fixed the crash
class documented in SMT_IF_PROJECT_DOC §9.4 #16, so that path must stay strict.

Some assets genuinely need to grow.  F0014 (the static font texture) is the
first: widening it from 208x252 to 252x252 lifts the static glyph limit from
1383 to 1763, which is what stops menu/skill/option text from running past the
glyph table.  The widened file no longer fits its 24576-byte slot.

The game locates its data through **FILEPOS.DAT**, its own table of
``{u32 LBA, u32 size}`` records -- 105 of its 106 entries match the ISO
directory exactly, so it is authoritative.  Relocation therefore means:

1. write the payload into blank sectors past the last file, and
2. rewrite that file's FILEPOS.DAT record to the new LBA and size.

The tail sectors are already well-formed Mode 2 Form 1 (valid sync, header and
subheader, zero user data), so they are written exactly like any other sector:
drop in the user data and rebuild EDC/ECC.
"""
import json
import struct
from pathlib import Path

from src.disc_injector import (
    MODE2_FORM1_USER_OFFSET,
    MODE2_FORM1_USER_SIZE,
    RAW_SECTOR_SIZE,
    load_manifest_entry,
    rebuild_mode2_form1_checksums,
    validate_existing_sector_checksums,
)

FILEPOS_PATH = "FILEPOS.DAT"
FILEPOS_RECORD_SIZE = 8

# CD-ROM XA subheader, stored twice at sector offset 16..24 as
# [file, channel, submode, coding].  The PS1's CD controller filters sectors by
# submode: without the Data bit (0x08) a sector is never handed to the data
# FIFO, so a read of it simply never completes -- the game hangs on a black
# screen even though the sector's EDC/ECC are perfectly valid.  The disc's blank
# tail sectors carry submode 0x00, so relocated payloads must stamp the real
# data submodes: 0x08 for every sector, and 0x89 (EOF | Data | EOR) on the last
# sector of a file, which is what every existing file on this disc uses.
SUBHEADER_OFFSET = 16
SUBHEADER_SIZE = 8
SUBMODE_DATA = 0x08
SUBMODE_LAST = 0x89


def _subheader(submode):
    half = bytes((0x00, 0x00, submode, 0x00))
    return half + half


def _sector_count(size):
    return (size + MODE2_FORM1_USER_SIZE - 1) // MODE2_FORM1_USER_SIZE


def _manifest_entries(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return [
        entry
        for entry in manifest.get("entries", ())
        if entry.get("path") and entry.get("kind") == "file"
    ]


def find_free_tail_lba(manifest_path, image_size):
    """First blank sector past every file the manifest knows about."""
    entries = _manifest_entries(manifest_path)
    end = max(
        entry["extent_lba"] + _sector_count(entry["size"])
        for entry in entries
    )
    if end * RAW_SECTOR_SIZE > image_size:
        raise ValueError("Manifest extends past the end of the disc image")
    return end


def plan_relocations(manifest_path, payloads, image_size):
    """Assign tail LBAs to ``{disc_path: bytes}``, largest first."""
    if not payloads:
        return []

    entries = {
        entry["path"]: entry for entry in _manifest_entries(manifest_path)
    }
    total_sectors = image_size // RAW_SECTOR_SIZE
    lba = find_free_tail_lba(manifest_path, image_size)

    plan = []
    for disc_path in sorted(payloads):
        payload = payloads[disc_path]
        if not isinstance(payload, bytes):
            raise ValueError(f"Relocated payload for {disc_path} must be bytes")
        if disc_path not in entries:
            raise KeyError(f"{disc_path} is not in the manifest")

        sectors = _sector_count(len(payload))
        if lba + sectors > total_sectors:
            raise ValueError(
                f"{disc_path} needs {sectors} sectors but only "
                f"{total_sectors - lba} blank sectors remain"
            )
        plan.append({
            "path": disc_path,
            "payload": payload,
            "lba": lba,
            "sectors": sectors,
            "original_lba": entries[disc_path]["extent_lba"],
            "original_size": entries[disc_path]["size"],
        })
        lba += sectors

    return plan


def patch_filepos(filepos_data, manifest_path, plan):
    """Point FILEPOS.DAT's records at the relocated payloads."""
    filepos_data = bytearray(filepos_data)
    if len(filepos_data) % FILEPOS_RECORD_SIZE:
        raise ValueError("FILEPOS.DAT size is not a multiple of 8 bytes")

    record_count = len(filepos_data) // FILEPOS_RECORD_SIZE
    for item in plan:
        matches = [
            index
            for index in range(record_count)
            if struct.unpack_from("<II", filepos_data, index * FILEPOS_RECORD_SIZE)
            == (item["original_lba"], item["original_size"])
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"{item['path']}: expected exactly one FILEPOS.DAT record for "
                f"LBA {item['original_lba']} size {item['original_size']}, "
                f"found {len(matches)}"
            )
        struct.pack_into(
            "<II",
            filepos_data,
            matches[0] * FILEPOS_RECORD_SIZE,
            item["lba"],
            len(item["payload"]),
        )
        item["filepos_index"] = matches[0]

    return bytes(filepos_data)


def _read_user_data(image_file, lba, sector_count):
    data = bytearray()
    for index in range(sector_count):
        image_file.seek(
            (lba + index) * RAW_SECTOR_SIZE + MODE2_FORM1_USER_OFFSET
        )
        data += image_file.read(MODE2_FORM1_USER_SIZE)
    return bytes(data)


def _iter_directory_records(image_file, lba, size):
    """Yield ``(absolute_offset, record)`` for one ISO9660 directory extent."""
    sectors = _sector_count(size)
    data = _read_user_data(image_file, lba, sectors)
    offset = 0
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset = (offset // MODE2_FORM1_USER_SIZE + 1) * MODE2_FORM1_USER_SIZE
            continue
        record = data[offset:offset + length]
        sector = lba + offset // MODE2_FORM1_USER_SIZE
        in_sector = offset % MODE2_FORM1_USER_SIZE
        absolute = (
            sector * RAW_SECTOR_SIZE + MODE2_FORM1_USER_OFFSET + in_sector
        )
        yield absolute, record
        offset += length


def _find_iso_record(image_file, disc_path):
    """Locate the ISO9660 directory record for ``D/F0014.BIN``-style paths."""
    pvd = _read_user_data(image_file, 16, 1)
    if pvd[1:6] != b"CD001" or pvd[0] != 1:
        raise ValueError("Primary volume descriptor not found at LBA 16")
    root = pvd[156:156 + 34]
    lba = struct.unpack_from("<I", root, 2)[0]
    size = struct.unpack_from("<I", root, 10)[0]

    parts = disc_path.replace("\\", "/").strip("/").split("/")
    for depth, part in enumerate(parts):
        target = part.casefold()
        found = None
        for absolute, record in _iter_directory_records(image_file, lba, size):
            name_length = record[32]
            name = bytes(record[33:33 + name_length])
            plain = name.split(b";")[0].decode("ascii", "replace").casefold()
            if plain != target:
                continue
            found = (absolute, record)
            break
        if found is None:
            raise KeyError(f"{disc_path}: {part} is not in the ISO directory")
        absolute, record = found
        lba = struct.unpack_from("<I", record, 2)[0]
        size = struct.unpack_from("<I", record, 10)[0]
        if depth == len(parts) - 1:
            return absolute, lba, size
    raise KeyError(disc_path)


def patch_iso_directory(image_path, plan):
    """Keep the ISO9660 directory in step with the relocated payloads.

    FILEPOS.DAT is what the game itself reads, but the ISO directory is what
    every other reader sees -- including whatever path the boot-time loader
    takes.  Leaving it pointing at the old extent means those readers get the
    stale copy, which no longer matches the patched font geometry.
    """
    image_path = Path(image_path)
    if not plan:
        return []

    with image_path.open("r+b") as image_file:
        for item in plan:
            absolute, lba, size = _find_iso_record(image_file, item["path"])
            if (lba, size) != (item["original_lba"], item["original_size"]):
                raise AssertionError(
                    f"{item['path']}: ISO record says LBA {lba} size {size}, "
                    f"expected {item['original_lba']}/{item['original_size']}"
                )
            new_lba = item["lba"]
            new_size = len(item["payload"])
            image_file.seek(absolute + 2)
            image_file.write(
                struct.pack("<I", new_lba) + struct.pack(">I", new_lba)
            )
            image_file.seek(absolute + 10)
            image_file.write(
                struct.pack("<I", new_size) + struct.pack(">I", new_size)
            )
            item["iso_record_offset"] = absolute

        image_file.flush()

    # The records live in ordinary Form 1 sectors, so their EDC/ECC must be
    # rebuilt just like any other edited sector.
    with image_path.open("r+b") as image_file:
        for item in plan:
            absolute = item["iso_record_offset"]
            sector_offset = (absolute // RAW_SECTOR_SIZE) * RAW_SECTOR_SIZE
            image_file.seek(sector_offset)
            sector = bytearray(image_file.read(RAW_SECTOR_SIZE))
            rebuild_mode2_form1_checksums(sector)
            image_file.seek(sector_offset)
            image_file.write(sector)
        image_file.flush()

    return plan


def write_relocations(image_path, plan):
    """Write relocated payloads into the blank tail sectors."""
    image_path = Path(image_path)
    if not plan:
        return []

    with image_path.open("r+b") as image_file:
        for item in plan:
            for sector_number in range(item["sectors"]):
                lba = item["lba"] + sector_number
                offset = lba * RAW_SECTOR_SIZE
                image_file.seek(offset)
                sector = bytearray(image_file.read(RAW_SECTOR_SIZE))
                if len(sector) != RAW_SECTOR_SIZE:
                    raise ValueError(f"Short sector at LBA {lba}")
                validate_existing_sector_checksums(sector, lba)

                submode = (
                    SUBMODE_LAST
                    if sector_number == item["sectors"] - 1
                    else SUBMODE_DATA
                )
                sector[
                    SUBHEADER_OFFSET:SUBHEADER_OFFSET + SUBHEADER_SIZE
                ] = _subheader(submode)

                start = sector_number * MODE2_FORM1_USER_SIZE
                chunk = item["payload"][start:start + MODE2_FORM1_USER_SIZE]
                user = MODE2_FORM1_USER_OFFSET
                sector[user:user + MODE2_FORM1_USER_SIZE] = chunk.ljust(
                    MODE2_FORM1_USER_SIZE,
                    b"\x00",
                )
                rebuild_mode2_form1_checksums(sector)

                image_file.seek(offset)
                image_file.write(sector)

        image_file.flush()

        # Read the payloads back the way the game will, straight off the disc.
        for item in plan:
            data = bytearray()
            for sector_number in range(item["sectors"]):
                lba = item["lba"] + sector_number
                image_file.seek(lba * RAW_SECTOR_SIZE + MODE2_FORM1_USER_OFFSET)
                data += image_file.read(MODE2_FORM1_USER_SIZE)
            if bytes(data[:len(item["payload"])]) != item["payload"]:
                raise AssertionError(
                    f"{item['path']}: relocated payload verification failed"
                )
            for sector_number in range(item["sectors"]):
                lba = item["lba"] + sector_number
                image_file.seek(lba * RAW_SECTOR_SIZE + SUBHEADER_OFFSET)
                expected = _subheader(
                    SUBMODE_LAST
                    if sector_number == item["sectors"] - 1
                    else SUBMODE_DATA
                )
                if image_file.read(SUBHEADER_SIZE) != expected:
                    raise AssertionError(
                        f"{item['path']}: LBA {lba} has the wrong subheader; "
                        "the CD controller would skip it"
                    )

    return plan
