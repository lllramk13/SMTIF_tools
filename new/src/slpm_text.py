import json
from pathlib import Path

from src.text_codec import encode_text, load_character_codes


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_TEXT_PATH = NEW_DIRECTORY / "data" / "slpm_text.json"
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"
STATIC_SECTION = "text_17"
VALID_RENDERERS = frozenset(("dynamic", "static"))


def _parse_offset(value, record_id):
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError(f"{record_id}: offset cannot be negative")
        return value

    if not isinstance(value, str) or not value:
        raise ValueError(f"{record_id}: offset must be a hexadecimal string")

    try:
        return int(value, 16)
    except ValueError as error:
        raise ValueError(
            f"{record_id}: invalid hexadecimal offset {value!r}"
        ) from error


def load_slpm_text_records(path=DEFAULT_TEXT_PATH):
    path = Path(path)
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict) or set(data) != {"text_slpm"}:
        raise ValueError(
            f"SLPM text JSON must contain only the text_slpm section: {path}"
        )

    raw_records = data["text_slpm"]
    if not isinstance(raw_records, list):
        raise ValueError("text_slpm must be a list")

    records = []
    seen_ids = set()
    seen_offsets = set()
    previous_end = -1
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            raise ValueError("text_slpm contains a non-object record")

        record_id = raw_record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("SLPM text record has an invalid id")
        if record_id in seen_ids:
            raise ValueError(f"duplicate SLPM text id: {record_id}")
        seen_ids.add(record_id)

        offset = _parse_offset(raw_record.get("offset"), record_id)
        if offset in seen_offsets:
            raise ValueError(f"duplicate SLPM text offset: {offset:#x}")
        seen_offsets.add(offset)

        max_bytes = raw_record.get("max_bytes")
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes < 2
            or max_bytes % 2
        ):
            raise ValueError(
                f"{record_id}: max_bytes must be a positive even integer"
            )

        source = raw_record.get("source")
        translation = raw_record.get("translation")
        renderer = raw_record.get("renderer")
        if not isinstance(source, str) or not source:
            raise ValueError(f"{record_id}: source must be a non-empty string")
        if not isinstance(translation, str):
            raise ValueError(f"{record_id}: translation must be a string")
        if renderer not in VALID_RENDERERS:
            raise ValueError(
                f"{record_id}: renderer must be dynamic or static"
            )

        if offset < previous_end:
            raise ValueError(f"{record_id}: SLPM text slots overlap")
        previous_end = offset + max_bytes

        records.append({
            "id": record_id,
            "offset": offset,
            "max_bytes": max_bytes,
            "source": source,
            "translation": translation,
            "renderer": renderer,
        })

    return tuple(records)


def translated_slpm_texts(records, renderer=None):
    if renderer is not None and renderer not in VALID_RENDERERS:
        raise ValueError(f"Unknown SLPM renderer: {renderer!r}")
    return tuple(
        record["translation"]
        for record in records
        if record["translation"]
        and (renderer is None or record["renderer"] == renderer)
    )


def build_slpm_text_patches(
    records,
    codetable_path=DEFAULT_CODETABLE_PATH,
    global_character_overrides=None,
    static_character_overrides=None,
):
    dynamic_character_codes = load_character_codes(codetable_path)
    dynamic_character_codes.update(global_character_overrides or {})
    static_character_codes = dict(dynamic_character_codes)
    static_character_codes.update(static_character_overrides or {})

    patches = []
    for record in records:
        translation = record["translation"]
        if not translation:
            continue

        character_codes = (
            dynamic_character_codes
            if record["renderer"] == "dynamic"
            else static_character_codes
        )

        try:
            encoded = encode_text(character_codes, translation)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{record['id']}: embedded SLPM text encoding failed: {error}"
            ) from error

        max_bytes = record["max_bytes"]
        if len(encoded) > max_bytes:
            raise ValueError(
                f"{record['id']}: encoded text needs {len(encoded)} bytes, "
                f"but the original slot has {max_bytes}"
            )

        padded = encoded + (b"\xFF" * (max_bytes - len(encoded)))
        patches.append({
            "id": record["id"],
            "offset": record["offset"],
            "max_bytes": max_bytes,
            "text": translation,
            "data": padded,
            "encoded_length": len(encoded),
        })

    return tuple(patches)
