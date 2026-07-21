def _block_key(record):
    if not isinstance(record, dict):
        raise ValueError("编码记录必须是对象")

    section = record.get("section")
    file_name = record.get("file_name")
    block_offset = record.get("block_offset")

    if not isinstance(section, str) or section == "":
        raise ValueError("编码记录缺少有效的section")
    if not isinstance(file_name, str) or file_name == "":
        raise ValueError("编码记录缺少有效的file_name")
    if not isinstance(block_offset, int) or isinstance(block_offset, bool):
        raise ValueError("编码记录缺少有效的block_offset")
    if block_offset < 0:
        raise ValueError("block_offset不能是负数")

    return section, file_name, block_offset


def group_records_by_block(encoded_records):
    if not isinstance(encoded_records, list):
        raise ValueError("encoded_records必须是列表")

    grouped_records = {}
    static_block_bases = {}

    for record in encoded_records:
        section, file_name, block_offset = _block_key(record)
        if section != "text_88":
            continue

        static_key = section, file_name
        current_base = static_block_bases.get(static_key)
        if current_base is None or block_offset < current_base:
            static_block_bases[static_key] = block_offset

    for record in encoded_records:
        section, file_name, block_offset = _block_key(record)
        if section == "text_88":
            block_offset = static_block_bases[(section, file_name)]

        key = section, file_name, block_offset
        grouped_records.setdefault(key, []).append(record)

    return grouped_records


def build_text_block(records):
    if not isinstance(records, list) or not records:
        raise ValueError("文本块记录必须是非空列表")

    section, file_name, block_offset = _block_key(records[0])
    is_static_block = section == "text_88"

    if is_static_block:
        records = sorted(records, key=lambda record: _block_key(record)[2])
        block_offset = min(_block_key(record)[2] for record in records)
        expected_slots = [block_offset + index * 4 for index in range(len(records))]
        actual_slots = [_block_key(record)[2] for record in records]
        if actual_slots != expected_slots:
            raise ValueError(
                f"{file_name}: text_88指针槽不是从0x{block_offset:X}开始的连续4字节表"
            )

    expected_key = section, file_name, block_offset
    unique_texts = {}

    for record in records:
        record_section, record_file_name, record_block_offset = _block_key(record)
        if is_static_block:
            if (record_section, record_file_name) != (section, file_name):
                raise ValueError("同一个静态文本块中不能包含不同文件的记录")
        elif (record_section, record_file_name, record_block_offset) != expected_key:
            raise ValueError("同一个文本块中不能包含不同文件或偏移的记录")

        record_id = record.get("id", "<unknown>")
        old_text_offset = record.get("old_text_offset")
        encoded_text = record.get("encoded_text")

        if not isinstance(old_text_offset, int) or isinstance(old_text_offset, bool):
            raise ValueError(f"{record_id}: old_text_offset必须是整数")
        if old_text_offset < 0:
            raise ValueError(f"{record_id}: old_text_offset不能是负数")
        if not isinstance(encoded_text, bytes):
            raise ValueError(f"{record_id}: encoded_text必须是bytes")
        if not encoded_text.endswith(b"\xFF\xFF"):
            raise ValueError(f"{record_id}: encoded_text缺少FFFF结束符")

        previous_text = unique_texts.get(old_text_offset)
        if previous_text is not None and previous_text != encoded_text:
            raise ValueError(
                f"{record_id}: 相同旧文本偏移对应了不同的编码文本 "
                f"(0x{old_text_offset:X})"
            )

        unique_texts.setdefault(old_text_offset, encoded_text)

    pointer_table_size = len(records) * 4
    text_data = bytearray()
    new_text_offsets = {}

    for old_text_offset in sorted(unique_texts):
        new_text_offset = pointer_table_size + len(text_data)
        if new_text_offset > 0xFFFFFFFF:
            raise ValueError(
                f"{file_name} 0x{block_offset:X}: 新文本偏移超出32位范围"
            )

        new_text_offsets[old_text_offset] = new_text_offset
        text_data.extend(unique_texts[old_text_offset])

    pointer_table = bytearray()

    for record in records:
        new_text_offset = new_text_offsets[record["old_text_offset"]]
        pointer_table.extend(new_text_offset.to_bytes(4, "little"))

    block_data = bytes(pointer_table + text_data)

    return {
        "kind": "static" if is_static_block else "resource",
        "section": section,
        "file_name": file_name,
        "block_offset": block_offset,
        "records": records,
        "record_count": len(records),
        "unique_text_count": len(unique_texts),
        "pointer_table_size": pointer_table_size,
        "pointer_table": bytes(pointer_table),
        "text_data": bytes(text_data),
        "new_text_offsets": new_text_offsets,
        "data": block_data,
    }


def build_text_blocks(encoded_records):
    grouped_records = group_records_by_block(encoded_records)
    return [
        build_text_block(records)
        for records in grouped_records.values()
    ]
