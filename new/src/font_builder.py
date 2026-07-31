import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
CODETABLE_PATH = HERE.parent / 'data' / 'codetable.json'
FONT_PATH = HERE.parents[2] / 'fusion-pixel-12px.otf'
# fusion-pixel covers 36,492 codepoints but not everything the translation
# reaches for -- 徯 (U+5FAF, 凫徯) and 镳 (U+9573) both render as tofu.  Rather
# than force the translators off a proper name, fall back to an outline font for
# just those characters.  SimSun at 13px thresholds the most legibly of the
# system fonts at this size; 12px turns both into blobs.
FALLBACK_FONT_PATH = Path('C:/Windows/Fonts/simsun.ttc')
FALLBACK_FONT_PX = 13

# A few glyphs are artwork, not text.  The Macca symbol lives at index 0x18 of
# the original 2bpp F13 and the text extractor could only label it ￡, so every
# 「￡{数值0}を手に入れた」 came out drawn as a literal pound sign.  Keep the
# original pixels instead of letting a font substitute a lookalike.
PRESERVED_ORIGINAL_GLYPHS = {'￡': 0x18}
ORIGINAL_F13_PATH = HERE.parents[2] / 'SMT IF' / 'extrac' / 'D' / 'F0013.BIN'
ORIGINAL_GLYPH_BYTES = 48   # 16x12 at 2bpp
# Palette index 0 is the visible ink; 1 and 2 are its antialias shades and 3 is
# transparent.  Our 1bpp font has no shades, so fold 0-1 into ink.
ORIGINAL_INK_MAX = 1


def load_original_glyph(index, path=None):
    """Convert one glyph of the original 2bpp F13 into our 1bpp format."""
    from src.compression import decompress_resource

    path = Path(path or ORIGINAL_F13_PATH)
    storage = decompress_resource(path.read_bytes())
    start = index * ORIGINAL_GLYPH_BYTES
    source = storage[start:start + ORIGINAL_GLYPH_BYTES]
    if len(source) != ORIGINAL_GLYPH_BYTES:
        raise ValueError(f'Original F13 has no glyph {index:#x}')

    glyph = bytearray(b'\xFF' * BYTES_PER_GLYPH)
    for y in range(GLYPH_H):
        for x in range(GLYPH_W):
            bit = (y * GLYPH_W + x) * 2
            value = (source[bit // 8] >> (bit % 8)) & 3
            if value <= ORIGINAL_INK_MAX:
                glyph[y * 2 + x // 8] &= ~(1 << (x % 8))
    return bytes(glyph)
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
    glyph_font_sizes=None,
):
    codetable = load_codetable(codetable_path)
    if glyph_overrides:
        codetable.update(glyph_overrides)
    font_path = Path(font_path)
    if not font_path.is_file():
        raise FileNotFoundError(f'Font file not found: {font_path}')

    glyph_font_sizes = dict(glyph_font_sizes or {})
    for index, font_size in glyph_font_sizes.items():
        if index not in codetable:
            raise ValueError(
                f'Font-size override refers to missing glyph index: {index:#x}'
            )
        if not isinstance(font_size, int) or isinstance(font_size, bool):
            raise ValueError(
                f'Glyph font size must be an integer: {index:#x}={font_size!r}'
            )
        if font_size <= 0:
            raise ValueError(
                f'Glyph font size must be positive: {index:#x}={font_size}'
            )

    fonts = {
        font_size: ImageFont.truetype(str(font_path), font_size)
        for font_size in ({FONT_PX} | set(glyph_font_sizes.values()))
    }

    # Characters the main font lacks come out as tofu, which is invisible to
    # every other build check.  Detect them by rendering a private-use codepoint
    # that cannot exist and comparing: anything that draws identically is the
    # .notdef box.
    fallback_font = None
    if FALLBACK_FONT_PATH.is_file():
        fallback_font = ImageFont.truetype(
            str(FALLBACK_FONT_PATH), FALLBACK_FONT_PX
        )
    tofu = render_glyph('󰀀', fonts[FONT_PX])
    fallback_used = []
    missing_without_fallback = []
    preserved = {
        character: load_original_glyph(index)
        for character, index in PRESERVED_ORIGINAL_GLYPHS.items()
    }
    preserved_used = []
    glyph_count = max(codetable) + 1
    font_data = bytearray(glyph_count * BYTES_PER_GLYPH)

    for index in range(glyph_count):
        start = index * BYTES_PER_GLYPH
        character = codetable[index]
        size = glyph_font_sizes.get(index, FONT_PX)
        if character in preserved and size == FONT_PX:
            font_data[start:start + BYTES_PER_GLYPH] = preserved[character]
            preserved_used.append((index, character))
            continue
        glyph = render_glyph(character, fonts[size])
        if glyph == tofu and size == FONT_PX:
            if fallback_font is None:
                missing_without_fallback.append((index, character))
            else:
                glyph = render_glyph(character, fallback_font)
                fallback_used.append((index, character))
        font_data[start:start + BYTES_PER_GLYPH] = glyph

    # In the original game glyph index 0 is empty: it is the blank slot the
    # name-entry UI inserts for a space (and that text uses for a full-width
    # space).  Our codetable must be contiguous, so a character necessarily
    # occupies index 0; force its glyph transparent (all bits set = background)
    # so a space renders blank instead of showing that stand-in character.
    font_data[0:BYTES_PER_GLYPH] = b'\xFF' * BYTES_PER_GLYPH

    expected_size = glyph_count * BYTES_PER_GLYPH
    if len(font_data) != expected_size:
        raise AssertionError(
            f'Font size mismatch: expected {expected_size}, got {len(font_data)}'
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(font_data)
    write_preview(font_data, glyph_count, preview_path)

    if missing_without_fallback:
        raise ValueError(
            'Font lacks these characters and no fallback font is available: '
            + ' '.join(
                f'{index:#x}={character}'
                for index, character in missing_without_fallback
            )
        )
    if preserved_used:
        print(
            f'Original artwork kept for {len(preserved_used)} glyph(s): '
            + ' '.join(
                f'{index:#x}=U+{ord(character):04X}'
                for index, character in preserved_used
            )
        )
    if fallback_used:
        # Console encodings here are not always UTF-8, and some of these are
        # invisible characters that crept into the translation, so report them
        # by codepoint rather than by glyph.
        print(
            f'Fallback font ({FALLBACK_FONT_PATH.name} @{FALLBACK_FONT_PX}px) '
            f'supplied {len(fallback_used)} glyph(s): '
            + ' '.join(
                f'{index:#x}=U+{ord(character):04X}'
                for index, character in fallback_used
            )
        )

    print(f'Rendered {glyph_count} glyphs')
    print(f'Font data: {output_path} ({len(font_data)} bytes)')
    print(f'Preview: {preview_path}')
    return bytes(font_data)



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
