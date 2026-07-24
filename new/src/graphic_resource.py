from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.compression import compress_rle, expand_rle_to_size


GRAPHIC_RLE_TYPE = b"\x02\x01"
GRAPHIC_HEADER_SIZE = 16


@dataclass(frozen=True)
class GraphicResource:
    resource_header: bytes
    declared_size: int
    reserved: bytes
    width_words: int
    height: int
    raw_data: bytes
    tail: bytes

    @property
    def pixel_width(self):
        # PS1 4bpp stores four pixels in each 16-bit VRAM word.
        return self.width_words * 4

    @property
    def expected_raw_size(self):
        return self.width_words * self.height * 2


def decompress_graphic_resource(resource):
    resource = bytes(resource)
    if len(resource) < GRAPHIC_HEADER_SIZE:
        raise ValueError("图像资源短于16字节头")
    if resource[:2] != GRAPHIC_RLE_TYPE:
        raise ValueError(f"不支持的图像资源类型: {resource[:4].hex().upper()}")

    declared_size = int.from_bytes(resource[4:8], "little")
    if not GRAPHIC_HEADER_SIZE <= declared_size <= len(resource):
        raise ValueError(
            f"无效的图像压缩块长度 {declared_size}; 文件长度 {len(resource)}"
        )

    width_words = int.from_bytes(resource[12:14], "little")
    height = int.from_bytes(resource[14:16], "little")
    expected_size = width_words * height * 2
    source = memoryview(resource)[GRAPHIC_HEADER_SIZE:declared_size]
    source_position = 0
    output = bytearray()

    while len(output) < expected_size:
        if source_position >= len(source):
            raise ValueError("图像RLE流提前结束")

        control = source[source_position]
        source_position += 1

        if control < 0x80:
            length = control + 1
            end = source_position + length
            if end > len(source):
                raise ValueError("图像RLE原文段超出压缩块")
            output.extend(source[source_position:end])
            source_position = end
        else:
            length = control - 0x7D
            if source_position >= len(source):
                raise ValueError("图像RLE重复段缺少数值字节")
            output.extend(bytes([source[source_position]]) * length)
            source_position += 1

        if len(output) > expected_size:
            raise ValueError("图像RLE解压结果超过头部声明尺寸")

    if source_position != len(source):
        raise ValueError("图像RLE达到目标长度后仍有未读取的压缩数据")

    return GraphicResource(
        resource_header=resource[:4],
        declared_size=declared_size,
        reserved=resource[8:12],
        width_words=width_words,
        height=height,
        raw_data=bytes(output),
        tail=resource[declared_size:],
    )


def rebuild_graphic_resource(
    original_resource,
    raw_data,
    width_words=None,
    height=None,
):
    """Rebuild a 0x02/0x01 graphic resource.

    By default the result keeps the original geometry *and* the original
    declared block size (the stream is padded back up), so the file can be
    injected in place.

    Passing ``width_words``/``height`` re-geometries the image instead.  The
    declared size then follows the new payload, so the file grows and the
    caller is responsible for placing it somewhere with room (see
    ``src/disc_relocation.py``).
    """
    original_resource = bytes(original_resource)
    original = decompress_graphic_resource(original_resource)
    raw_data = bytes(raw_data)

    resized = width_words is not None or height is not None
    if width_words is None:
        width_words = original.width_words
    if height is None:
        height = original.height
    expected_raw_size = width_words * height * 2

    if len(raw_data) != expected_raw_size:
        raise ValueError(
            f"图像原始数据应为 {expected_raw_size} 字节，"
            f"实际为 {len(raw_data)} 字节"
        )

    if resized:
        return _rebuild_resized_graphic(
            original_resource,
            original,
            raw_data,
            width_words,
            height,
        )

    # The 0x02/0x01 payload uses the exact same token stream as 0x01/0x01.
    # Reuse the verified encoder, then replace its 12-byte generic header with
    # the graphic resource's 16-byte header.
    generic_rle = compress_rle(raw_data)
    target_generic_size = original.declared_size - (
        GRAPHIC_HEADER_SIZE - 12
    )
    if len(generic_rle) > target_generic_size:
        raise ValueError(
            f"Rebuilt graphic stream is {len(generic_rle) + 4} bytes, "
            f"but the original declared block is only "
            f"{original.declared_size} bytes"
        )
    if len(generic_rle) < target_generic_size:
        generic_rle = expand_rle_to_size(
            generic_rle,
            target_generic_size,
        )

    payload = generic_rle[12:]
    declared_size = original.declared_size

    header = b"".join((
        original.resource_header,
        declared_size.to_bytes(4, "little"),
        original.reserved,
        original.width_words.to_bytes(2, "little"),
        original.height.to_bytes(2, "little"),
    ))
    rebuilt = b"".join((
        header,
        payload,
        original_resource[original.declared_size:],
    ))

    if len(rebuilt) != len(original_resource):
        raise AssertionError("图像资源重建后文件长度发生变化")
    if (
        rebuilt[original.declared_size:]
        != original_resource[original.declared_size:]
    ):
        raise AssertionError("Rebuilt graphic resource changed its file tail")
    if decompress_graphic_resource(rebuilt).raw_data != raw_data:
        raise AssertionError("图像资源RLE往返校验失败")

    return rebuilt


def _rebuild_resized_graphic(
    original_resource,
    original,
    raw_data,
    width_words,
    height,
):
    """Rebuild a graphic resource with new dimensions (the file grows)."""
    generic_rle = compress_rle(raw_data)
    payload = generic_rle[12:]

    declared_size = GRAPHIC_HEADER_SIZE + len(payload)

    # F0014 carries a second resource (the CLUT) after the image, and the
    # original starts it on a 4-byte boundary -- declared size 0x5BF5 plus three
    # filler bytes lands it at 0x5BF8.  A resource scanner walks the file by
    # 4-aligned declared sizes, so the follow-on resource has to stay aligned or
    # it is simply not found (which costs the palette, i.e. a black screen).
    # The filler cannot go inside the stream -- the decompressor rejects any
    # unread bytes -- so it goes between the resource and the tail, exactly like
    # the original, but sized for the new declared size.
    filler = b"\x00" * (-declared_size % 4)
    tail_start = original.declared_size + (-original.declared_size % 4)
    header = b"".join((
        original.resource_header,
        declared_size.to_bytes(4, "little"),
        original.reserved,
        width_words.to_bytes(2, "little"),
        height.to_bytes(2, "little"),
    ))
    rebuilt = b"".join((
        header,
        payload,
        filler,
        original_resource[tail_start:],
    ))

    check = decompress_graphic_resource(rebuilt)
    if check.raw_data != raw_data:
        raise AssertionError("重建的加宽图像RLE往返校验失败")
    if (check.width_words, check.height) != (width_words, height):
        raise AssertionError("重建的加宽图像尺寸不正确")
    aligned_end = declared_size + len(filler)
    if aligned_end % 4:
        raise AssertionError("重建的加宽图像尾部未4字节对齐")
    if rebuilt[aligned_end:] != original_resource[tail_start:]:
        raise AssertionError("重建的加宽图像破坏了文件尾部")

    return rebuilt


def unpack_4bpp_pixels(raw_data, width, height):
    raw_data = bytes(raw_data)
    expected_size = width * height // 2
    if width % 2:
        raise ValueError("4bpp图像宽度必须为偶数")
    if len(raw_data) != expected_size:
        raise ValueError(
            f"4bpp数据应为 {expected_size} 字节，实际为 {len(raw_data)}"
        )

    pixels = bytearray(width * height)
    for pixel_index in range(width * height):
        packed = raw_data[pixel_index // 2]
        pixels[pixel_index] = (
            packed & 0x0F
            if pixel_index % 2 == 0
            else packed >> 4
        )
    return bytes(pixels)


def pack_4bpp_pixels(pixels, width, height):
    pixels = bytes(pixels)
    if width % 2:
        raise ValueError("4bpp图像宽度必须为偶数")
    if len(pixels) != width * height:
        raise ValueError(
            f"像素数据应为 {width * height} 字节，实际为 {len(pixels)}"
        )

    output = bytearray(width * height // 2)
    for pixel_index, value in enumerate(pixels):
        if value > 0x0F:
            raise ValueError(f"4bpp像素超出0–15范围: {value}")
        if pixel_index % 2 == 0:
            output[pixel_index // 2] = value
        else:
            output[pixel_index // 2] |= value << 4
    return bytes(output)


def write_graphic_preview(resource_data, output_path, scale=2):
    graphic = decompress_graphic_resource(resource_data)
    pixels = unpack_4bpp_pixels(
        graphic.raw_data,
        graphic.pixel_width,
        graphic.height,
    )
    image = Image.frombytes(
        "L",
        (graphic.pixel_width, graphic.height),
        bytes(value * 17 for value in pixels),
    )
    if scale != 1:
        image = image.resize(
            (image.width * scale, image.height * scale),
            resample=Image.Resampling.NEAREST,
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def verify_exact_roundtrip(resource_path):
    resource_path = Path(resource_path)
    original = resource_path.read_bytes()
    graphic = decompress_graphic_resource(original)
    rebuilt = rebuild_graphic_resource(original, graphic.raw_data)
    if rebuilt != original:
        raise AssertionError(f"原样重建未能逐字节还原: {resource_path}")
    return graphic
