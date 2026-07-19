from pathlib import Path

from compression import (
    compress_rle,
    compress_lz77_non_overlapping,
    decompress_resource,
    expand_lz77_to_size,
    verify_lz77_roundtrip,
)


HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
RAW_FONT_PATH = HERE.parent / 'build' / 'font_1bpp.bin'
ORIGINAL_F13_PATH = PROJECT_DIR / 'extrac' / 'D' / 'F0013.BIN'
OUTPUT_F13_PATH = HERE.parent / 'build' / 'F0013.BIN'


def build_f13(
    raw_font_path=RAW_FONT_PATH,
    original_f13_path=ORIGINAL_F13_PATH,
    output_path=OUTPUT_F13_PATH,
    non_overlapping=False,
    compression='lz77',
):
    raw_font_path = Path(raw_font_path)
    original_f13_path = Path(original_f13_path)
    output_path = Path(output_path)

    font_data = raw_font_path.read_bytes()
    original_f13 = original_f13_path.read_bytes()
    original_font_storage = decompress_resource(original_f13)
    if len(font_data) > len(original_font_storage):
        raise ValueError(
            f'New font data is {len(font_data)} bytes, but the original '
            f'decompressed F13 has only {len(original_font_storage)} bytes'
        )

    # F13 contains more glyph slots than the translated font replaces.  Keep
    # the untouched original slots instead of blanking them: system/title
    # text can still reference those indices.
    rebuilt_font_storage = bytearray(original_font_storage)
    rebuilt_font_storage[:len(font_data)] = font_data
    rebuilt_font_storage = bytes(rebuilt_font_storage)
    if compression == 'rle':
        compressed = compress_rle(rebuilt_font_storage)
        if decompress_resource(compressed) != rebuilt_font_storage:
            raise AssertionError('RLE roundtrip failed')
    elif non_overlapping:
        compressed = compress_lz77_non_overlapping(rebuilt_font_storage)
        if decompress_resource(compressed) != rebuilt_font_storage:
            raise AssertionError('Non-overlapping LZ77 roundtrip failed')
    elif compression == 'lz77':
        compressed = verify_lz77_roundtrip(rebuilt_font_storage)
    else:
        raise ValueError(f'Unsupported compression method: {compression!r}')

    expected_magic = {
        'lz77': b'\x01\x02\x00\x00',
        'rle': b'\x01\x01\x00\x00',
    }[compression]
    if compressed[:4] != expected_magic:
        raise AssertionError('Compressed F13 has the wrong resource header')

    original_declared_size = int.from_bytes(original_f13[4:8], 'little')
    if compression == 'lz77' and len(compressed) < original_declared_size:
        compressed = expand_lz77_to_size(
            compressed.ljust(original_declared_size, b'\x00'),
            original_declared_size,
        )
    if compression == 'lz77' and len(compressed) != original_declared_size:
        raise ValueError(
            f'Rebuilt LZ77 block must keep the original declared size '
            f'{original_declared_size}, got {len(compressed)}'
        )

    if len(compressed) > original_declared_size:
        raise ValueError(
            f'Compressed main F13 resource is {len(compressed)} bytes, but '
            f'the original main resource has only {original_declared_size}'
        )

    # Bytes after the main resource are not disposable padding.  Original
    # F0013 contains a second 22-byte compressed resource there (32 raw bytes,
    # consistent with a 16-colour PS1 CLUT).  Preserve the entire tail.
    rebuilt_f13 = b''.join((
        compressed.ljust(original_declared_size, b'\x00'),
        original_f13[original_declared_size:],
    ))
    if len(rebuilt_f13) != len(original_f13):
        raise AssertionError('Rebuilt F13 changed the file size')
    if decompress_resource(rebuilt_f13) != rebuilt_font_storage:
        raise AssertionError('Rebuilt F13 failed decompression verification')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rebuilt_f13)

    print(f'Active font data: {len(font_data)} bytes')
    print(f'Decompressed F13: {len(rebuilt_font_storage)} bytes')
    print(
        f'Preserved original glyph slots: '
        f'{(len(rebuilt_font_storage) - len(font_data)) // 24}'
    )
    print(f'Compressed block: {len(compressed)} bytes')
    print(f'F0013 output: {len(rebuilt_f13)} bytes')
    print(
        f'Preserved file tail: '
        f'{len(original_f13) - original_declared_size} bytes'
    )
    print(f'Output: {output_path}')
    return rebuilt_f13


if __name__ == '__main__':
    build_f13()
