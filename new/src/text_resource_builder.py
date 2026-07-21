from pathlib import Path

from src.compression import (
    compress_lz77,
    decompress_resource,
    pack_uncompressed,
)


SUPPORTED_RESOURCE_TYPES = {
    b"\x01\x00",
    b"\x01\x01",
    b"\x01\x02",
}


# Some event scripts keep direct offsets to strings inside these resources.
# Their pointer tables and text slots therefore have to remain at the original
# offsets; rebuilding them as a compact pointer-table + text blob breaks those
# external references even though the rebuilt pointer table itself is valid.
FIXED_LAYOUT_RESOURCE_KEYS = set()

# Replacing this resource together with other F0018 resources makes the map
# loader hang even when all original string offsets and lengths are retained.
# Keep it byte-for-byte original until its non-text references are understood.
PASSTHROUGH_RESOURCE_KEYS = {
    ("F0018", 0x1F5C),
}

# This entry is also consumed sequentially outside the normal pointer-table
# path.  Its terminator must stay at the original end position; padding after
# an earlier FFFF makes the map loader interpret the gap as data.
EXACT_SIZE_RECORD_IDS = {
    "F0018-00001F5C-00000358",
}


def read_resource_info(file_data, block_offset):
    if not isinstance(file_data, bytes):
        raise ValueError("file_data必须是bytes")
    if not isinstance(block_offset, int) or isinstance(block_offset, bool):
        raise ValueError("block_offset必须是整数")
    if block_offset < 0 or block_offset + 8 > len(file_data):
        raise ValueError(f"资源偏移超出文件范围: 0x{block_offset:X}")

    header = file_data[block_offset:block_offset + 8]
    resource_type = header[:2]
    resource_id = header[2:4]
    total_size = int.from_bytes(header[4:8], "little")

    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise ValueError(
            f"0x{block_offset:X}: 不支持的资源类型 {header[:4].hex().upper()}"
        )
    if total_size < 8:
        raise ValueError(f"0x{block_offset:X}: 无效资源长度 {total_size}")

    resource_end = block_offset + total_size
    if resource_end > len(file_data):
        raise ValueError(
            f"0x{block_offset:X}: 资源结束位置超出文件范围 "
            f"(0x{resource_end:X} > 0x{len(file_data):X})"
        )

    resource_data = file_data[block_offset:resource_end]
    raw_data = decompress_resource(resource_data)

    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "total_size": total_size,
        "data": resource_data,
        "raw_data": raw_data,
    }


def _set_resource_id(resource_data, resource_id):
    if not isinstance(resource_id, bytes) or len(resource_id) != 2:
        raise ValueError("resource_id必须是2字节")

    resource_data = bytearray(resource_data)
    resource_data[2:4] = resource_id
    return bytes(resource_data)


def pack_text_resource(raw_data, resource_id=b"\x00\x00"):
    if not isinstance(raw_data, bytes):
        raise ValueError("raw_data必须是bytes")

    compressed_resource = _set_resource_id(
        compress_lz77(raw_data),
        resource_id,
    )
    uncompressed_resource = _set_resource_id(
        pack_uncompressed(raw_data),
        resource_id,
    )

    if len(compressed_resource) <= len(uncompressed_resource):
        resource_data = compressed_resource
    else:
        resource_data = uncompressed_resource

    if decompress_resource(resource_data) != raw_data:
        raise AssertionError("文本资源压缩后无法正确还原")

    return resource_data


def build_fixed_layout_raw_data(block, original_raw_data):
    records = block.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("固定布局文本块缺少编码记录")

    record_count = len(records)
    pointer_table_size = record_count * 4
    if pointer_table_size > len(original_raw_data):
        raise ValueError("固定布局文本块的原指针表超出解压数据")

    original_pointers = [
        int.from_bytes(original_raw_data[position:position + 4], "little")
        for position in range(0, pointer_table_size, 4)
    ]
    record_pointers = [record["old_text_offset"] for record in records]
    if record_pointers != original_pointers:
        raise ValueError(
            f"{block['file_name']} 0x{block['block_offset']:X}: "
            "JSON记录顺序或旧文本偏移与原指针表不一致"
        )

    unique_offsets = sorted(set(original_pointers))
    slot_ends = {
        offset: (
            unique_offsets[index + 1]
            if index + 1 < len(unique_offsets)
            else len(original_raw_data)
        )
        for index, offset in enumerate(unique_offsets)
    }

    output = bytearray(original_raw_data)
    written_texts = {}

    for record in records:
        record_id = record.get("id", "<unknown>")
        text_offset = record["old_text_offset"]
        encoded_text = record["encoded_text"]
        slot_end = slot_ends[text_offset]
        slot_size = slot_end - text_offset

        if text_offset < pointer_table_size or slot_end > len(output):
            raise ValueError(
                f"{record_id}: 固定布局文本槽超出原始解压数据"
            )
        if len(encoded_text) > slot_size:
            raise ValueError(
                f"{record_id}: 固定布局文本超出旧槽 "
                f"({len(encoded_text)} > {slot_size}，超出"
                f"{len(encoded_text) - slot_size}字节)"
            )
        if (
            record_id in EXACT_SIZE_RECORD_IDS
            and len(encoded_text) != slot_size
        ):
            raise ValueError(
                f"{record_id}: 此文本必须保持原编码长度 "
                f"({len(encoded_text)} != {slot_size})"
            )

        previous_text = written_texts.get(text_offset)
        if previous_text is not None and previous_text != encoded_text:
            raise ValueError(
                f"{record_id}: 共用固定槽的记录编码结果不一致"
            )
        if previous_text is not None:
            continue

        output[text_offset:slot_end] = (
            encoded_text + b"\x00" * (slot_size - len(encoded_text))
        )
        written_texts[text_offset] = encoded_text

    if output[:pointer_table_size] != original_raw_data[:pointer_table_size]:
        raise AssertionError("固定布局重建意外修改了原指针表")
    if len(output) != len(original_raw_data):
        raise AssertionError("固定布局重建改变了解压数据长度")

    return bytes(output)


def build_text_resources(text_blocks, source_directory):
    if not isinstance(text_blocks, list):
        raise ValueError("text_blocks必须是列表")

    source_directory = Path(source_directory)
    file_cache = {}
    built_resources = []

    for block in text_blocks:
        block_kind = block.get("kind")
        if block_kind == "static":
            continue
        if block_kind != "resource":
            raise ValueError(f"未知文本块类型: {block_kind!r}")

        file_name = block.get("file_name")
        block_offset = block.get("block_offset")
        raw_data = block.get("data")

        if (file_name, block_offset) in PASSTHROUGH_RESOURCE_KEYS:
            continue

        if not isinstance(file_name, str) or file_name == "":
            raise ValueError("文本块缺少有效的file_name")
        if not isinstance(raw_data, bytes):
            raise ValueError(f"{file_name}: 文本块data必须是bytes")

        source_path = source_directory / f"{file_name}.BIN"
        if source_path not in file_cache:
            if not source_path.is_file():
                raise FileNotFoundError(f"找不到原始文件: {source_path}")
            file_cache[source_path] = source_path.read_bytes()

        original_info = read_resource_info(
            file_cache[source_path],
            block_offset,
        )
        fixed_layout = (
            file_name,
            block_offset,
        ) in FIXED_LAYOUT_RESOURCE_KEYS
        if fixed_layout:
            raw_data = build_fixed_layout_raw_data(
                block,
                original_info["raw_data"],
            )
        resource_data = pack_text_resource(
            raw_data,
            original_info["resource_id"],
        )

        built_resources.append({
            "section": block["section"],
            "file_name": file_name,
            "block_offset": block_offset,
            "resource_id": original_info["resource_id"],
            "original_type": original_info["resource_type"],
            "original_size": original_info["total_size"],
            "raw_size": len(raw_data),
            "resource_type": resource_data[:2],
            "resource_size": len(resource_data),
            "fixed_layout": fixed_layout,
            "data": resource_data,
        })

    return built_resources
