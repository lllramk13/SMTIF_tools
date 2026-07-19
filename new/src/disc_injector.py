import argparse
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
DEFAULT_IMAGE_PATH = (
    PROJECT_DIR
    / 'Game'
    / 'modified'
    / 'Shin Megami Tensei If... (Japan).bin'
)
DEFAULT_MANIFEST_PATH = PROJECT_DIR / 'extrac' / '_iso_manifest.json'

RAW_SECTOR_SIZE = 2352
MODE2_FORM1_USER_OFFSET = 24
MODE2_FORM1_USER_SIZE = 2048
SYNC_PATTERN = b'\x00' + b'\xFF' * 10 + b'\x00'


def _build_edc_lut():
    table = []
    for value in range(256):
        entry = value
        for _ in range(8):
            entry = (entry >> 1) ^ (0xD8018001 if entry & 1 else 0)
        table.append(entry)
    return table


def _build_ecc_luts():
    forward = [0] * 256
    backward = [0] * 256
    for value in range(256):
        doubled = value << 1
        if doubled & 0x100:
            doubled ^= 0x11D
        forward[value] = doubled
        backward[value ^ doubled] = value
    return forward, backward


EDC_LUT = _build_edc_lut()
ECC_FORWARD_LUT, ECC_BACKWARD_LUT = _build_ecc_luts()


def compute_edc(data: bytes) -> int:
    edc = 0
    for value in data:
        edc = (edc >> 8) ^ EDC_LUT[(edc ^ value) & 0xFF]
    return edc


def compute_ecc(
    source: bytes,
    major_count: int,
    minor_count: int,
    major_multiplier: int,
    minor_increment: int,
) -> bytes:
    expected_size = major_count * minor_count
    if len(source) < expected_size:
        raise ValueError(
            f'ECC source requires {expected_size} bytes, got {len(source)}'
        )

    first = bytearray(major_count)
    second = bytearray(major_count)

    for major in range(major_count):
        index = (major >> 1) * major_multiplier + (major & 1)
        ecc_a = 0
        ecc_b = 0

        for _ in range(minor_count):
            value = source[index]
            index += minor_increment
            if index >= expected_size:
                index -= expected_size
            ecc_a ^= value
            ecc_b ^= value
            ecc_a = ECC_FORWARD_LUT[ecc_a]

        ecc_a = ECC_BACKWARD_LUT[ECC_FORWARD_LUT[ecc_a] ^ ecc_b]
        first[major] = ecc_a
        second[major] = ecc_a ^ ecc_b

    return bytes(first + second)


def validate_mode2_form1_sector(sector: bytes, lba: int) -> None:
    if len(sector) != RAW_SECTOR_SIZE:
        raise ValueError(f'LBA {lba}: sector is not {RAW_SECTOR_SIZE} bytes')
    if sector[:12] != SYNC_PATTERN:
        raise ValueError(f'LBA {lba}: invalid raw-sector sync pattern')
    if sector[15] != 2:
        raise ValueError(f'LBA {lba}: expected Mode 2, got mode {sector[15]}')
    if sector[16:20] != sector[20:24]:
        raise ValueError(f'LBA {lba}: duplicated XA subheaders do not match')
    if sector[18] & 0x20:
        raise ValueError(f'LBA {lba}: Mode 2 Form 2 sector is not supported')


def rebuild_mode2_form1_checksums(sector: bytearray) -> None:
    if len(sector) != RAW_SECTOR_SIZE:
        raise ValueError(f'Sector must contain {RAW_SECTOR_SIZE} bytes')

    edc = compute_edc(sector[0x10:0x818])
    sector[0x818:0x81C] = edc.to_bytes(4, 'little')

    # Mode 2 ECC treats the address/mode bytes as zero while generating parity.
    address_and_mode = bytes(sector[0x0C:0x10])
    sector[0x0C:0x10] = b'\x00\x00\x00\x00'
    sector[0x81C:0x8C8] = compute_ecc(
        sector[0x0C:0x81C], 86, 24, 2, 86
    )
    sector[0x8C8:0x930] = compute_ecc(
        sector[0x0C:0x8C8], 52, 43, 86, 88
    )
    sector[0x0C:0x10] = address_and_mode


def validate_existing_sector_checksums(sector: bytes, lba: int) -> None:
    validate_mode2_form1_sector(sector, lba)
    rebuilt = bytearray(sector)
    rebuild_mode2_form1_checksums(rebuilt)
    if rebuilt[0x818:0x930] != sector[0x818:0x930]:
        raise ValueError(f'LBA {lba}: existing EDC/ECC verification failed')


def load_manifest_entry(manifest_path, disc_path: str):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    normalized_target = disc_path.replace('\\', '/').strip('/').casefold()

    matches = [
        entry
        for entry in manifest.get('entries', [])
        if entry.get('path', '').replace('\\', '/').strip('/').casefold()
        == normalized_target
    ]
    if not matches:
        raise KeyError(f'File is not present in manifest: {disc_path}')
    if len(matches) != 1:
        raise ValueError(f'Manifest contains duplicate paths: {disc_path}')

    entry = matches[0]
    if entry.get('kind') != 'file':
        raise ValueError(f'Manifest path is not a file: {disc_path}')
    if entry.get('extraction') != 'mode2-form1-2048':
        raise ValueError(
            f'Unsupported extraction type for {disc_path}: '
            f'{entry.get("extraction")}'
        )

    if manifest.get('raw_sector_size') != RAW_SECTOR_SIZE:
        raise ValueError('Manifest raw-sector size does not match 2352 bytes')
    if manifest.get('form1_user_offset') != MODE2_FORM1_USER_OFFSET:
        raise ValueError('Manifest Form 1 user offset does not match 24 bytes')
    if manifest.get('form1_user_size') != MODE2_FORM1_USER_SIZE:
        raise ValueError('Manifest Form 1 user size does not match 2048 bytes')

    return entry


def extract_file_from_image(image_file, entry) -> bytes:
    remaining = entry['size']
    lba = entry['extent_lba']
    output = bytearray()

    image_file.seek(lba * RAW_SECTOR_SIZE)
    while remaining:
        sector = image_file.read(RAW_SECTOR_SIZE)
        validate_mode2_form1_sector(sector, lba)
        chunk_size = min(remaining, MODE2_FORM1_USER_SIZE)
        output.extend(
            sector[
                MODE2_FORM1_USER_OFFSET:
                MODE2_FORM1_USER_OFFSET + chunk_size
            ]
        )
        remaining -= chunk_size
        lba += 1

    return bytes(output)


def replace_file_in_image(
    image_path,
    manifest_path,
    disc_path: str,
    replacement_path,
):
    image_path = Path(image_path)
    replacement_path = Path(replacement_path)
    entry = load_manifest_entry(manifest_path, disc_path)
    replacement = replacement_path.read_bytes()

    if len(replacement) != entry['size']:
        raise ValueError(
            f'Replacement for {entry["path"]} must be exactly '
            f'{entry["size"]} bytes, got {len(replacement)}'
        )
    if image_path.stat().st_size % RAW_SECTOR_SIZE:
        raise ValueError('Disc image size is not a multiple of 2352 bytes')

    sector_count = (len(replacement) + MODE2_FORM1_USER_SIZE - 1) // 2048
    final_lba = entry['extent_lba'] + sector_count
    if final_lba * RAW_SECTOR_SIZE > image_path.stat().st_size:
        raise ValueError('Replacement extends beyond the end of the disc image')

    with image_path.open('r+b') as image_file:
        for sector_number in range(sector_count):
            lba = entry['extent_lba'] + sector_number
            sector_offset = lba * RAW_SECTOR_SIZE
            image_file.seek(sector_offset)
            sector = bytearray(image_file.read(RAW_SECTOR_SIZE))
            validate_existing_sector_checksums(sector, lba)

            source_offset = sector_number * MODE2_FORM1_USER_SIZE
            chunk = replacement[
                source_offset:source_offset + MODE2_FORM1_USER_SIZE
            ]
            user_start = MODE2_FORM1_USER_OFFSET
            sector[user_start:user_start + len(chunk)] = chunk
            rebuild_mode2_form1_checksums(sector)

            image_file.seek(sector_offset)
            image_file.write(sector)

        image_file.flush()
        extracted = extract_file_from_image(image_file, entry)

    if extracted != replacement:
        raise AssertionError(
            f'Post-write verification failed for {entry["path"]}'
        )

    print(f'Replaced: {entry["path"]}')
    print(f'LBA range: {entry["extent_lba"]}..{final_lba - 1}')
    print(f'Sectors updated: {sector_count}')
    print(f'Bytes replaced: {len(replacement)}')
    print(f'Image: {image_path}')


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Replace a Mode 2 Form 1 file inside a raw PS1 BIN image.'
    )
    parser.add_argument('disc_path', help='Manifest path, e.g. D/F0013.BIN')
    parser.add_argument('replacement', type=Path, help='Replacement file path')
    parser.add_argument('--image', type=Path, default=DEFAULT_IMAGE_PATH)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST_PATH)
    return parser.parse_args()


if __name__ == '__main__':
    arguments = parse_arguments()
    replace_file_in_image(
        image_path=arguments.image,
        manifest_path=arguments.manifest,
        disc_path=arguments.disc_path,
        replacement_path=arguments.replacement,
    )
