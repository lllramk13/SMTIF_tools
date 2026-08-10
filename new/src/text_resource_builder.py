from pathlib import Path

from src.compression import (
    compress_lz77,
    decompress_resource,
    expand_lz77_to_size,
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
FIXED_LAYOUT_RESOURCE_KEYS = {
    # Post-Amdusias jar event.  The event reads the first string directly at
    # raw + 0x18 instead of following pointer-table entry 0.  Letting the
    # overflowing Chinese string move to the resource tail makes the fixed
    # offset decode the pointer table as glyphs and eventually corrupt RAM.
    ("F0016", 0x5E0C4),
}

# Some dialogue resources enter through the pointer table once, then advance
# from the current FFFF terminator to the following record without consulting
# the next pointer-table entry.  Relocating only an overflowing record to the
# end of such a resource breaks that sequential chain: the first page renders,
# but advancing reads beyond the resource as glyph codes and corrupts the
# dynamic-font cache.  These blocks must therefore use the compact rebuild,
# which keeps every encoded record contiguous in pointer-table order.
COMPACT_RESOURCE_KEYS = {
    # Mammon's pre-battle dialogue.  Record 0x1C grows by four bytes in Chinese;
    # the old allow-growth layout moved it to the tail while record 0x66 stayed
    # in place, causing the button-advance freeze at 0x8005BCEC/0x8005BD0C.
    ("F0016", 0x38990),
}

# Partial tail relocation is opt-in, never a generic fallback.  These are
# lookup/menu tables whose internal offsets must remain stable; their entries
# are fetched independently, so pointer order is not used as dialogue state.
# All ordinary event/dialogue blocks fall back to a compact rebuild when a
# translation does not fit its original slot.
ALLOW_GROWTH_RESOURCE_KEYS = {
    # F0017 contains special/static lookup text.
    ("F0017", 0x0),
    # F0094 contains name, item, skill and description lookup tables used by
    # menus through fixed internal offsets.
    ("F0094", 0x3C),
    ("F0094", 0x2D98),
    ("F0094", 0x39F8),
}

# Replacing this resource together with other F0018 resources makes the map
# loader hang even when all original string offsets and lengths are retained.
# Keep it byte-for-byte original until its non-text references are understood.
# F0040 (menu name/label tables): the guardian screen and other menus read
# this file by absolute offsets; the run repacker moving/compressing its four
# resources made the game jump through corrupted data (PC=0x00020002 freeze),
# so all four blocks are rebuilt strictly in place instead.
PASSTHROUGH_RESOURCE_KEYS = {
    ("F0018", 0x1F5C),
    ("F0040", 0x0),
    ("F0040", 0xB84),
    ("F0040", 0x207C),
    ("F0040", 0x3120),
}

# These passthrough resources are additionally patched IN PLACE after the
# normal rebuild: same offset, same declared total size, fixed string layout
# (pointer table and every string slot stay at their original offsets), so
# nothing else in the file shifts.  The map-loader hang above was caused by
# the run repacker moving resources; a byte-budget in-place swap avoids it.
INPLACE_RESOURCE_KEYS = {
    ("F0018", 0x1F5C),
    ("F0040", 0x0),
    ("F0040", 0xB84),
    ("F0040", 0x207C),
    ("F0040", 0x3120),
}

# Padding code appended before the FFFF terminator when an exact-size record's
# translation is shorter than its slot (0x0000 renders as a blank glyph).
INPLACE_PAD_CODE = b"\x00\x00"

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


def build_fixed_layout_raw_data(
    block,
    original_raw_data,
    allow_growth=False,
):
    """Rebuild a resource keeping every string at its original offset.

    The game reads menu/option strings by fixed offsets inside the decompressed
    resource, so a compact repack (which moves every string) breaks them.  This
    keeps the original pointer table and writes each translation back into its
    original slot.

    With ``allow_growth`` the buffer may be extended: translations that no
    longer fit their original slot are appended past the end of the original
    data and their pointer-table entries are repointed there.  Every string
    that still fits stays exactly where it was, so this moves only the handful
    of overflowing strings instead of all of them like the compact fallback
    does.  The resource header's decompressed-size field follows the new
    length, and the file-level exact-size pass still pins the compressed
    resource to its original size.
    """
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
    relocated_offsets = {}

    for record in records:
        record_id = record.get("id", "<unknown>")
        text_offset = record["old_text_offset"]
        encoded_text = record["encoded_text"]
        slot_end = slot_ends[text_offset]
        slot_size = slot_end - text_offset

        if text_offset < pointer_table_size or slot_end > len(original_raw_data):
            raise ValueError(
                f"{record_id}: 固定布局文本槽超出原始解压数据"
            )
        if len(encoded_text) > slot_size:
            if not allow_growth:
                raise ValueError(
                    f"{record_id}: 固定布局文本超出旧槽 "
                    f"({len(encoded_text)} > {slot_size}，超出"
                    f"{len(encoded_text) - slot_size}字节)"
                )
            if record_id in EXACT_SIZE_RECORD_IDS:
                raise ValueError(
                    f"{record_id}: 此文本必须保持原编码长度，不能外移"
                )
            previous_text = written_texts.get(text_offset)
            if previous_text is not None and previous_text != encoded_text:
                raise ValueError(
                    f"{record_id}: 共用固定槽的记录编码结果不一致"
                )
            if text_offset not in relocated_offsets:
                if len(output) % 2:
                    output.append(0)
                relocated_offsets[text_offset] = len(output)
                output.extend(encoded_text)
                written_texts[text_offset] = encoded_text
            continue
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

    for index, pointer in enumerate(original_pointers):
        new_offset = relocated_offsets.get(pointer)
        if new_offset is None:
            continue
        output[index * 4:index * 4 + 4] = new_offset.to_bytes(4, "little")

    for index, pointer in enumerate(original_pointers):
        expected = relocated_offsets.get(pointer, pointer)
        actual = int.from_bytes(output[index * 4:index * 4 + 4], "little")
        if actual != expected:
            raise AssertionError(
                f"固定布局重建的指针表第{index}项不正确 "
                f"({actual:#x} != {expected:#x})"
            )

    if not relocated_offsets:
        if len(output) != len(original_raw_data):
            raise AssertionError("固定布局重建改变了解压数据长度")
    elif len(output) < len(original_raw_data):
        raise AssertionError("固定布局扩容后数据反而变短")

    unrelocated = [
        offset for offset in unique_offsets if offset not in relocated_offsets
    ]
    for offset in unrelocated:
        text = written_texts.get(offset)
        if text is None:
            continue
        if bytes(output[offset:offset + len(text)]) != text:
            raise AssertionError(
                f"固定布局文本未留在原偏移 {offset:#x}"
            )

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
        # Prefer FIXED internal layout for every block: it keeps each string at
        # its original in-resource offset (and the pointer table valid), so both
        # ways the game reads a resource work — sequential/pointer-table AND the
        # menus/options/confirms that read strings by a HARDCODED internal offset
        # (F0084 negotiation, F0075 level-up confirm, F0040 guardian…).  Compact
        # rebuilding shifts those offsets and breaks the fixed-offset readers.
        # Fixed layout is only possible when the block's records are in original
        # pointer-table order and every translation fits its original slot; when
        # it can't (mostly long dialogue that grew), fall back to the compact
        # `block["data"]` — safe because those are read via the pointer table.
        fixed_layout = False
        resource_key = (file_name, block_offset)
        if resource_key in COMPACT_RESOURCE_KEYS:
            raw_data = block["data"]
        elif resource_key not in FIXED_LAYOUT_RESOURCE_KEYS:
            # Prefer the strictest layout that works: every string in its
            # original slot; then the same but with overflowing strings
            # appended past the end; only then the compact repack, which
            # moves every string and so breaks fixed-offset menu reads.
            growth_modes = (
                (False, True)
                if resource_key in ALLOW_GROWTH_RESOURCE_KEYS
                else (False,)
            )
            for allow_growth in growth_modes:
                try:
                    candidate = build_fixed_layout_raw_data(
                        block,
                        original_info["raw_data"],
                        allow_growth=allow_growth,
                    )
                except (ValueError, KeyError):
                    continue
                if allow_growth:
                    # Growing only pays off if the resource still compresses
                    # into its original slot; otherwise the file-level
                    # exact-size pass would have to move later resources.
                    packed = pack_text_resource(
                        candidate,
                        original_info["resource_id"],
                    )
                    if len(packed) > original_info["total_size"]:
                        continue
                raw_data = candidate
                fixed_layout = True
                break
            else:
                raw_data = block["data"]
        else:
            raw_data = build_fixed_layout_raw_data(
                block,
                original_info["raw_data"],
            )
            fixed_layout = True
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


def _pad_exact_size_records(block, original_raw_data):
    """Return the block with exact-size records padded to fill their slots.

    The padding inserts blank-glyph codes before the FFFF terminator so the
    terminator stays at the original end of the slot, which the sequential
    consumer of these records requires.
    """
    records = block.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("原地文本块缺少编码记录")

    pointer_table_size = len(records) * 4
    original_pointers = [
        int.from_bytes(original_raw_data[position:position + 4], "little")
        for position in range(0, pointer_table_size, 4)
    ]
    unique_offsets = sorted(set(original_pointers))
    slot_ends = {
        offset: (
            unique_offsets[index + 1]
            if index + 1 < len(unique_offsets)
            else len(original_raw_data)
        )
        for index, offset in enumerate(unique_offsets)
    }

    padded_records = []
    for record in records:
        record = dict(record)
        record_id = record.get("id", "<unknown>")
        if record_id in EXACT_SIZE_RECORD_IDS:
            slot_size = slot_ends[record["old_text_offset"]] - record["old_text_offset"]
            encoded_text = record["encoded_text"]
            padding = slot_size - len(encoded_text)
            if padding < 0:
                raise ValueError(
                    f"{record_id}: 译文超出原槽 {-padding} 字节，需要缩短"
                )
            if padding % 2:
                raise ValueError(f"{record_id}: 槽位剩余空间不是2的倍数")
            if padding:
                record["encoded_text"] = (
                    encoded_text[:-2]
                    + INPLACE_PAD_CODE * (padding // 2)
                    + encoded_text[-2:]
                )
        padded_records.append(record)

    block = dict(block)
    block["records"] = padded_records
    return block


def build_inplace_resource_patches(text_blocks, source_directory):
    """Build same-size replacement resources for INPLACE_RESOURCE_KEYS.

    Each patch keeps the resource's offset, declared total size, pointer
    table, and every string-slot offset identical to the original file, so
    no other byte in the file moves.
    """
    source_directory = Path(source_directory)
    blocks_by_key = {
        (block["file_name"], block["block_offset"]): block
        for block in text_blocks
        if block.get("kind") == "resource"
    }
    patches = []

    for file_name, block_offset in sorted(INPLACE_RESOURCE_KEYS):
        block = blocks_by_key.get((file_name, block_offset))
        if block is None:
            raise ValueError(
                f"{file_name} 0x{block_offset:X}: 原地补丁缺少对应文本块"
            )

        source_path = source_directory / f"{file_name}.BIN"
        original_file = source_path.read_bytes()
        original_info = read_resource_info(original_file, block_offset)
        original_raw = original_info["raw_data"]
        original_total = original_info["total_size"]

        padded_block = _pad_exact_size_records(block, original_raw)
        new_raw = build_fixed_layout_raw_data(padded_block, original_raw)

        if original_info["resource_type"] == b"\x01\x00":
            # Uncompressed resource: keep the original 8-byte header and
            # splice the fixed-layout raw directly, so the file layout stays
            # byte-for-byte identical apart from the string contents.
            if len(new_raw) != original_total - 8:
                raise AssertionError(
                    f"{file_name} 0x{block_offset:X}: 原地未压缩资源大小不一致"
                )
            compressed = (
                bytes(original_info["data"][:8]) + new_raw
            )
        else:
            compressed = compress_lz77(new_raw)
            if len(compressed) > original_total:
                raise ValueError(
                    f"{file_name} 0x{block_offset:X}: 压缩后超出原资源大小 "
                    f"({len(compressed)} > {original_total})"
                )
            if len(compressed) < original_total:
                padded_buffer = compressed + b"\x00" * (
                    original_total - len(compressed)
                )
                compressed = expand_lz77_to_size(padded_buffer, original_total)

            compressed = bytearray(compressed)
            compressed[2:4] = original_info["resource_id"]
            compressed = bytes(compressed)

        if len(compressed) != original_total:
            raise AssertionError(
                f"{file_name} 0x{block_offset:X}: 原地资源大小不一致"
            )
        if decompress_resource(compressed) != new_raw:
            raise AssertionError(
                f"{file_name} 0x{block_offset:X}: 原地资源解压回读不一致"
            )

        patches.append({
            "file_name": file_name,
            "block_offset": block_offset,
            "original_size": original_total,
            "original_region": original_info["data"],
            "data": compressed,
        })

    return patches


def apply_inplace_resource_patches(replacements, patches, source_directory):
    """Splice in-place patches into the rebuilt disc replacement files."""
    source_directory = Path(source_directory)

    for patch in patches:
        file_name = patch["file_name"]
        key = f"D/{file_name}.BIN"
        base = replacements.get(key)
        if base is None:
            base = (source_directory / f"{file_name}.BIN").read_bytes()

        offset = patch["block_offset"]
        size = patch["original_size"]
        if base[offset:offset + size] != patch["original_region"]:
            raise ValueError(
                f"{file_name} 0x{offset:X}: 重建文件中该资源已被移动或修改，"
                "无法原地替换"
            )

        replacements[key] = (
            base[:offset] + patch["data"] + base[offset + size:]
        )

    return replacements
