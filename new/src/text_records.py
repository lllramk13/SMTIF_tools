import json
from pathlib import Path

from src.text_codec import encode_text


def load_text_data(json_path):
    json_path = Path(json_path)

    with json_path.open("r", encoding="utf-8") as file:
        text_data = json.load(file)

    if not isinstance(text_data, dict):
        raise ValueError(f"文本JSON的根节点必须是对象: {json_path}")

    for section, records in text_data.items():
        if not isinstance(section, str):
            raise ValueError("文本JSON的分区名称必须是字符串")
        if not isinstance(records, list):
            raise ValueError(f"分区 {section!r} 的内容必须是列表")

    return text_data


def choose_text(record):
    if not isinstance(record, dict):
        raise ValueError("文本记录必须是对象")

    record_id = record.get("id", "<unknown>")
    translation = record.get("translation")

    if isinstance(translation, str) and translation != "":
        return translation

    source = record.get("source")

    if isinstance(source, str) and source != "":
        return source

    raise ValueError(f"{record_id}: 原文和译文均无效")


def _parse_hex_field(record, field_name):
    record_id = record.get("id", "<unknown>")
    value = record.get(field_name)

    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError(f"{record_id}: {field_name} 不能是负数")
        return int(str(value), 16)

    if not isinstance(value, str) or value == "":
        raise ValueError(
            f"{record_id}: {field_name} 必须是非负整数或十六进制字符串"
        )

    try:
        return int(value, 16)
    except ValueError as error:
        raise ValueError(
            f"{record_id}: {field_name} 不是有效的十六进制数 ({value!r})"
        ) from error


def encode_records(
    text_data,
    character_codes,
    section_character_codes=None,
):
    if not isinstance(text_data, dict):
        raise ValueError("text_data 必须是由 load_text_data 返回的对象")

    encoded_records = []
    section_character_codes = section_character_codes or {}

    for section, records in text_data.items():
        if not isinstance(records, list):
            raise ValueError(f"分区 {section!r} 的内容必须是列表")

        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"分区 {section!r} 中存在非对象记录")

            record_id = record.get("id")
            if not isinstance(record_id, str):
                raise ValueError(f"分区 {section!r} 中存在无效的记录ID")

            id_parts = record_id.split("-")
            if len(id_parts) != 3 or not id_parts[0]:
                raise ValueError(f"无效的记录ID: {record_id!r}")

            file_name, id_block_offset, id_text_offset = id_parts
            block_offset = _parse_hex_field(record, "block_offset")
            old_text_offset = _parse_hex_field(record, "pointer_offset")

            try:
                id_block_offset_value = int(id_block_offset, 16)
                id_text_offset_value = int(id_text_offset, 16)
            except ValueError as error:
                raise ValueError(f"记录ID包含无效的十六进制数: {record_id!r}") from error

            if id_block_offset_value != block_offset:
                raise ValueError(
                    f"{record_id}: ID与block_offset字段不一致"
                )

            if id_text_offset_value != old_text_offset:
                raise ValueError(
                    f"{record_id}: ID与pointer_offset字段不一致"
                )

            text = choose_text(record)

            active_character_codes = section_character_codes.get(
                section,
                character_codes,
            )

            try:
                encoded_text = encode_text(active_character_codes, text)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{record_id}: 文本编码失败: {error}") from error

            encoded_records.append({
                "id": record_id,
                "section": section,
                "file_name": file_name,
                "block_offset": block_offset,
                "old_text_offset": old_text_offset,
                "text": text,
                "encoded_text": encoded_text,
            })

    return encoded_records
