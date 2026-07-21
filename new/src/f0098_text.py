import json
from pathlib import Path

from src.text_codec import encode_text, load_character_codes


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_TEXT_PATH = NEW_DIRECTORY / "data" / "f0098_text.json"
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"

# F0098 is not a compressed resource with a pointer table: it is a flat run
# of fixed-position FFFF-terminated strings inside the file (races, item
# categories, equipment slots).  Each record's "offset" is a raw byte offset
# into F0098.BIN itself (not a RAM address), and "max_bytes" is the original
# Japanese string's byte length including its trailing FFFF.  A translation
# must fit in that same slot; the tail is padded with FF like the SLPM
# embedded-text slots.
DEFAULT_ORIGINAL_PATH = (
    NEW_DIRECTORY.parent / "extrac" / "D" / "F0098.BIN"
)


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


def load_f0098_text_records(path=DEFAULT_TEXT_PATH):
    path = Path(path)
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict) or set(data) != {"text_f0098"}:
        raise ValueError(
            f"F0098 text JSON must contain only the text_f0098 section: {path}"
        )

    raw_records = data["text_f0098"]
    if not isinstance(raw_records, list):
        raise ValueError("text_f0098 must be a list")

    records = []
    seen_ids = set()
    seen_offsets = set()
    previous_end = -1
    for raw_record in sorted(
        raw_records, key=lambda item: _parse_offset(item.get("offset"), item.get("id"))
    ):
        if not isinstance(raw_record, dict):
            raise ValueError("text_f0098 contains a non-object record")

        record_id = raw_record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("F0098 text record has an invalid id")
        if record_id in seen_ids:
            raise ValueError(f"duplicate F0098 text id: {record_id}")
        seen_ids.add(record_id)

        offset = _parse_offset(raw_record.get("offset"), record_id)
        if offset in seen_offsets:
            raise ValueError(f"duplicate F0098 text offset: {offset:#x}")
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
        if not isinstance(source, str) or not source:
            raise ValueError(f"{record_id}: source must be a non-empty string")
        if not isinstance(translation, str):
            raise ValueError(f"{record_id}: translation must be a string")

        if offset < previous_end:
            raise ValueError(f"{record_id}: F0098 text slots overlap")
        previous_end = offset + max_bytes

        records.append({
            "id": record_id,
            "offset": offset,
            "max_bytes": max_bytes,
            "source": source,
            "translation": translation,
        })

    return tuple(records)


def translated_f0098_texts(records):
    return tuple(
        record["translation"] for record in records if record["translation"]
    )


def build_f0098_text_patches(
    records,
    codetable_path=DEFAULT_CODETABLE_PATH,
    global_character_overrides=None,
):
    character_codes = load_character_codes(codetable_path)
    character_codes.update(global_character_overrides or {})

    patches = []
    for record in records:
        translation = record["translation"]
        if not translation:
            continue

        try:
            encoded = encode_text(character_codes, translation)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{record['id']}: F0098 text encoding failed: {error}"
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
        })

    return tuple(patches)


def apply_f0098_text_patches(
    original_data,
    patches,
    original_path=DEFAULT_ORIGINAL_PATH,
):
    """Patch a copy of F0098.BIN's bytes with the encoded translations.

    Each slot is verified against the original file before being
    overwritten, guarding against an offset that has drifted out of sync
    with the current extracted F0098.BIN.
    """
    original_reference = Path(original_path).read_bytes()
    if len(original_data) != len(original_reference):
        raise ValueError("F0098.BIN base data does not match extrac reference")

    patched = bytearray(original_data)
    for patch in patches:
        offset = patch["offset"]
        max_bytes = patch["max_bytes"]
        end = offset + max_bytes
        if end > len(patched):
            raise ValueError(f"{patch['id']}: F0098 text slot exceeds file size")

        current_slot = bytes(patched[offset:end])
        reference_slot = original_reference[offset:end]
        if current_slot != reference_slot:
            raise AssertionError(
                f"{patch['id']}: F0098.BIN slot does not match the clean "
                f"reference; refusing to overwrite unexpected data"
            )

        patched[offset:end] = patch["data"]

    return bytes(patched)
