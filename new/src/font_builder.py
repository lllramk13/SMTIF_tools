import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
CODETABLE_PATH = HERE.parent / 'data' / 'codetable.json'
FONT_PATH = HERE.parents[2] / 'fusion-pixel-12px.otf'
BUILD_DIR = HERE.parent / 'build'
FONT_OUTPUT_PATH = BUILD_DIR / 'font_1bpp.bin'
PREVIEW_OUTPUT_PATH = BUILD_DIR / 'font_preview.png'

GLYPH_W = 16
GLYPH_H = 12
DRAW_W = 12
FONT_PX = 12
THRESHOLD = 96
BYTES_PER_GLYPH = GLYPH_W * GLYPH_H // 8


def read_json(path):
    with Path(path).open('r', encoding='utf-8') as json_file:
        return json.load(json_file)


def code_to_index(code: str) -> int:
    try:
        code_bytes = bytes.fromhex(code)
    except ValueError as error:
        raise ValueError(f'Invalid codetable hex key: {code!r}') from error

    if len(code_bytes) != 2:
        raise ValueError(f'Codetable key must contain two bytes: {code!r}')
    return int.from_bytes(code_bytes, 'little')


def load_codetable(path=CODETABLE_PATH):
    raw_codetable = read_json(path)
    index_to_character = {}

    for code, character in raw_codetable.items():
        index = code_to_index(code)
        if index in index_to_character:
            raise ValueError(f'Duplicate glyph index: {index}')
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(
                f'Glyph index {index} must map to exactly one character: '
                f'{character!r}'
            )
        index_to_character[index] = character

    if not index_to_character:
        raise ValueError('Codetable is empty')

    highest_index = max(index_to_character)
    missing_indices = sorted(set(range(highest_index + 1)) - index_to_character.keys())
    if missing_indices:
        raise ValueError(f'Codetable has missing glyph indices: {missing_indices[:16]}')

    return index_to_character


def pack_1bpp(image: Image.Image) -> bytes:
    """Pack IF's 1bpp glyph: 0 is ink and 1 is transparent background.

    CN.asm expands a clear bit to palette index 0 and a set bit to palette
    index 4.  In IF's dynamic-font palette, index 0 is the visible text colour
    and index 4 is transparent.  Bit 0 is the leftmost pixel of each byte.
    """
    if image.size != (GLYPH_W, GLYPH_H):
        raise ValueError(
            f'Glyph image must be {GLYPH_W}x{GLYPH_H}, got {image.size}'
        )

    glyph = bytearray(b'\xFF' * BYTES_PER_GLYPH)
    for y in range(GLYPH_H):
        for x in range(GLYPH_W):
            if image.getpixel((x, y)) > THRESHOLD:
                glyph[y * 2 + x // 8] &= ~(1 << (x % 8))
    return bytes(glyph)


def unpack_1bpp(glyph: bytes) -> Image.Image:
    if len(glyph) != BYTES_PER_GLYPH:
        raise ValueError(
            f'Glyph must contain {BYTES_PER_GLYPH} bytes, got {len(glyph)}'
        )

    image = Image.new('L', (GLYPH_W, GLYPH_H), 0)
    pixels = image.load()
    for y in range(GLYPH_H):
        for x in range(GLYPH_W):
            byte_value = glyph[y * 2 + x // 8]
            if not byte_value & (1 << (x % 8)):
                pixels[x, y] = 255
    return image


def render_glyph(character: str, font: ImageFont.FreeTypeFont) -> bytes:
    image = Image.new('L', (GLYPH_W, GLYPH_H), 0)
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), character, font=font)
    width = right - left
    height = bottom - top

    x = (DRAW_W - width) // 2 - left
    y = (GLYPH_H - height) // 2 - top
    draw.text((x, y), character, fill=255, font=font)
    return pack_1bpp(image)


def write_preview(font_data: bytes, glyph_count: int, output_path, columns=32):
    rows = (glyph_count + columns - 1) // columns
    preview = Image.new('L', (columns * GLYPH_W, rows * GLYPH_H), 0)

    for index in range(glyph_count):
        start = index * BYTES_PER_GLYPH
        glyph = unpack_1bpp(font_data[start:start + BYTES_PER_GLYPH])
        x = index % columns * GLYPH_W
        y = index // columns * GLYPH_H
        preview.paste(glyph, (x, y))

    preview = preview.resize(
        (preview.width * 2, preview.height * 2),
        resample=Image.Resampling.NEAREST,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path)


def render_font(
    output_path=FONT_OUTPUT_PATH,
    preview_path=PREVIEW_OUTPUT_PATH,
    codetable_path=CODETABLE_PATH,
    font_path=FONT_PATH,
    glyph_overrides=None,
):
    codetable = load_codetable(codetable_path)
    if glyph_overrides:
        codetable.update(glyph_overrides)
    font_path = Path(font_path)
    if not font_path.is_file():
        raise FileNotFoundError(f'Font file not found: {font_path}')

    font = ImageFont.truetype(str(font_path), FONT_PX)
    glyph_count = max(codetable) + 1
    font_data = bytearray(glyph_count * BYTES_PER_GLYPH)

    for index in range(glyph_count):
        start = index * BYTES_PER_GLYPH
        font_data[start:start + BYTES_PER_GLYPH] = render_glyph(
            codetable[index], font
        )

    expected_size = glyph_count * BYTES_PER_GLYPH
    if len(font_data) != expected_size:
        raise AssertionError(
            f'Font size mismatch: expected {expected_size}, got {len(font_data)}'
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(font_data)
    write_preview(font_data, glyph_count, preview_path)

    print(f'Rendered {glyph_count} glyphs')
    print(f'Font data: {output_path} ({len(font_data)} bytes)')
    print(f'Preview: {preview_path}')
    return bytes(font_data)


def _show(glyph: bytes) -> None:
    image = unpack_1bpp(glyph)
    for y in range(GLYPH_H):
        row = ''.join(
            '█' if image.getpixel((x, y)) else '·'
            for x in range(GLYPH_W)
        )
        print(f'  {row}')


def _selftest() -> None:
    test_image = Image.new('L', (GLYPH_W, GLYPH_H), 0)
    for x in (0, 7, 8, 15):
        test_image.putpixel((x, 0), 255)
    packed = pack_1bpp(test_image)
    assert packed[:2] == b'\x7E\x7E', '1bpp bit order/polarity is incorrect'
    assert unpack_1bpp(packed).tobytes() == test_image.tobytes()


if __name__ == '__main__':
    _selftest()
    render_font()
