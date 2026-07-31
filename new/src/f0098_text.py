import json
from pathlib import Path

from src.text_codec import encode_text, load_character_codes


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_TEXT_PATH = NEW_DIRECTORY / "data" / "f0098_text.json"
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"

# F0098 is not a compressed resource with a pointer table: it is a flat run
# of fixed-position FFFF-terminated strings inside the file (races, item
# categories, equipment slots and action-name insertions).  Each record's
# "offset" is a raw byte offset into F0098.BIN itself (not a RAM address), and
# "max_bytes" is the original Japanese string's byte length including its
# trailing FFFF.
DEFAULT_ORIGINAL_PATH = (
    NEW_DIRECTORY.parent / "extrac" / "D" / "F0098.BIN"
)
F14_ACTION_NAME_START = 0x0906
F14_ACTION_NAME_END = 0x0C06


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

    valid_sections = {"text_f0098", "text_f0098_static"}
    if (
        not isinstance(data, dict)
        or "text_f0098" not in data
        or not set(data) <= valid_sections
    ):
        raise ValueError(
            "F0098 text JSON must contain text_f0098 and may contain "
            f"text_f0098_static: {path}"
        )

    section_records = []
    for section, raw_records in data.items():
        if not isinstance(raw_records, list):
            raise ValueError(f"{section} must be a list")
        default_renderer = (
            "static" if section == "text_f0098_static" else "dynamic"
        )
        section_records.extend(
            (raw_record, default_renderer)
            for raw_record in raw_records
        )

    records = []
    seen_ids = set()
    seen_offsets = set()
    previous_end = -1
    for raw_record, default_renderer in sorted(
        section_records,
        key=lambda item: _parse_offset(
            item[0].get("offset"), item[0].get("id")
        ),
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
        renderer = raw_record.get("renderer", default_renderer)
        # This flat table is inserted by control codes inside the same F14
        # action-result box as the surrounding SLPM sentence.  Old records
        # predate renderer metadata and were labelled dynamic, so identify the
        # complete contiguous table by its verified file range.
        if F14_ACTION_NAME_START <= offset < F14_ACTION_NAME_END:
            renderer = "static"
        if not isinstance(source, str) or not source:
            raise ValueError(f"{record_id}: source must be a non-empty string")
        if not isinstance(translation, str):
            raise ValueError(f"{record_id}: translation must be a string")
        if renderer not in {"dynamic", "static"}:
            raise ValueError(
                f"{record_id}: renderer must be dynamic or static"
            )

        if offset < previous_end:
            raise ValueError(f"{record_id}: F0098 text slots overlap")
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


def translated_f0098_texts(records, renderer=None):
    if renderer is not None and renderer not in {"dynamic", "static"}:
        raise ValueError(f"Unknown F0098 renderer: {renderer!r}")
    return tuple(
        record["translation"]
        for record in records
        if (
            record["translation"]
            and (renderer is None or record["renderer"] == renderer)
        )
    )


def build_f0098_text_patches(
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

        try:
            character_codes = (
                static_character_codes
                if record["renderer"] == "static"
                else dynamic_character_codes
            )
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

        # Every original slot ends with exactly one terminator.  Filling the
        # tail with 0xFF instead turns the leftover into a run of extra FFFF
        # terminators, which a menu that walks a run of adjacent slots reads
        # as phantom empty entries (the map-marker list has five such slots
        # in a row).  Pad ahead of a single terminator instead; glyph 0 is
        # forced fully transparent, so the filler never shows.
        if (max_bytes - len(encoded)) % 2:
            raise ValueError(
                f"{record['id']}: slot remainder is not a multiple of 2"
            )
        padded = (
            encoded[:-2]
            + bytes(2) * ((max_bytes - len(encoded)) // 2)
            + bytes((0xFF, 0xFF))
        )
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
