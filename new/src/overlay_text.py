"""In-place text injector for MIPS event-script overlays (F0049/F0092...).

These resources are executable code with FFFF-terminated Japanese strings
embedded at fixed offsets that the code references directly.  Strings can be
translated only by overwriting them in place: the resource keeps its exact
byte size and every non-string byte (code, pointers) stays untouched, so no
offset shifts and the map/event loader keeps working.

Data file (data/overlay_text.json)::

    {
      "F0049": [
        {"id": "...", "resource_offset": "00007874", "raw_offset": "000004F8",
         "byte_len": 22, "max_bytes": 22, "source": "...", "translation": "..."},
        ...
      ],
      ...
    }

Only records whose ``translation`` differs from ``source`` are injected;
untranslated rows are left as the original Japanese.
"""

import json
from pathlib import Path

from src.text_codec import encode_text
from src.text_resource_builder import read_resource_info


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_OVERLAY_TEXT_PATH = NEW_DIRECTORY / "data" / "overlay_text.json"

TERMINATOR = b"\xFF\xFF"
# 0x0000 renders as a blank glyph; used to pad a short translation so the
# terminator stays at the original slot end and nothing after it shifts.
PAD_CODE = b"\x00\x00"


def load_overlay_text_records(path=DEFAULT_OVERLAY_TEXT_PATH):
    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("overlay_text.json 顶层必须是 {文件名: [记录]}")
    return data


def translated_overlay_texts(records=None):
    """Every overlay translation that will actually be injected.

    Untranslated rows carry the Japanese source in ``translation``; only rows
    that differ from their source are injected, so only those contribute
    characters.  The codetable layout and the unified plan both need this or a
    character used *only* in overlay text looks unused to them and can be
    parked on a reserved name-entry code, where the original-UI glyph override
    then paints a kana over it.
    """
    if records is None:
        records = load_overlay_text_records()
    texts = []
    for rows in records.values():
        for row in rows:
            translation = row.get("translation") or ""
            if translation and translation != (row.get("source") or ""):
                texts.append(translation)
    return tuple(texts)


# A slot whose original text carries a page break, a wait or a newline is a
# *message*: the code points at it directly and reads until the terminator.
# Everything else is a menu entry, and menus walk a run of consecutive slots.
MESSAGE_CONTROL_CODES = ("{FF01}", "{FF02}", "{FF03}", "{FF92}")


def _is_message(source):
    return any(code in (source or "") for code in MESSAGE_CONTROL_CODES)


def _encode_slot(character_codes, translation, byte_len, record_id,
                 source=None):
    # encode_text already appends the FFFF terminator, so `encoded` is the
    # complete string.  Budgeting must not add a second one or every record
    # silently loses two bytes of its slot.
    encoded = encode_text(character_codes, translation)
    if not encoded.endswith(TERMINATOR):
        raise AssertionError(f"{record_id}: 编码结果缺少结束符")
    if len(encoded) > byte_len:
        raise ValueError(
            f"{record_id}: 译文编码 {len(encoded)} 字节超出原槽 {byte_len} "
            f"(超 {len(encoded) - byte_len})，需缩短"
        )
    remainder = byte_len - len(encoded)
    if remainder % 2:
        raise ValueError(f"{record_id}: 槽位剩余空间不是2的倍数")
    if not remainder:
        return encoded

    # Menus walk a run of consecutive slots, so their terminator has to stay at
    # the very end of the slot: laid out as `text FFFF 0000... FFFF` the walker
    # reads the option *plus* a trailing empty one, which inflates e.g. the
    # healing-elf menu (six of its options are padded) and runs the selection
    # index off the end.  Padding ahead of a single terminator avoids that.
    if not _is_message(source):
        return (
            encoded[:-len(TERMINATOR)]
            + PAD_CODE * (remainder // 2)
            + TERMINATOR
        )

    # Messages are the opposite case, and pre-terminator padding actively
    # breaks them.  The engine reads until FFFF, so those transparent glyphs
    # are *printed* first -- 75 of them for the appraisal shop's explanation --
    # which scrolls the window instead of waiting for a button, and a wait code
    # no longer adjacent to the terminator stops pausing at all.  src/slpm_text
    # hit exactly this on the action-result block (FF92 FFFF -> FF92 0000 FFFF)
    # and solved it the same way.
    #
    # Nothing walks past a message slot, so ending the string early and leaving
    # the rest of the slot as filler is safe -- and unlike the earlier attempt,
    # no second terminator is written, so no phantom entry can appear.
    return encoded + PAD_CODE * (remainder // 2)


def apply_overlay_text_patches(
    replacements,
    character_codes,
    source_directory,
    overlay_records=None,
):
    """Splice in-place translations into the overlay files.

    ``replacements`` is the disc-replacement mapping ("D/Fxxxx.BIN" -> bytes);
    each overlay file is patched from that mapping (or the clean source file)
    and written back.  Returns (patched_file_count, patched_string_count).
    """
    if overlay_records is None:
        overlay_records = load_overlay_text_records()

    source_directory = Path(source_directory)
    file_count = 0
    string_count = 0

    for file_name, records in overlay_records.items():
        translated = [
            record for record in records
            if str(record.get("translation", "")) != str(record.get("source", ""))
            and str(record.get("translation", "")).strip() != ""
        ]
        if not translated:
            continue

        key = f"D/{file_name}.BIN"
        base = replacements.get(key)
        if base is None:
            base = (source_directory / f"{file_name}.BIN").read_bytes()
        output = bytearray(base)

        # Group by resource so the clean resource body is validated once.
        clean_file = (source_directory / f"{file_name}.BIN").read_bytes()
        resource_raw_cache = {}

        for record in translated:
            record_id = record.get("id", "<unknown>")
            byte_len = int(record["byte_len"])

            if "file_offset" in record:
                # Direct file offset: text embedded straight in the raw overlay
                # (F0049's shop + healing menus span both inside and outside the
                # 0x0100 resource, so a single flat offset covers everything).
                file_offset = int(record["file_offset"], 16)
                original_slot = clean_file[file_offset:file_offset + byte_len]
            else:
                # Legacy form: offset relative to an uncompressed resource body.
                resource_offset = int(record["resource_offset"], 16)
                raw_offset = int(record["raw_offset"], 16)
                if resource_offset not in resource_raw_cache:
                    info = read_resource_info(clean_file, resource_offset)
                    if info["resource_type"] != b"\x01\x00":
                        raise ValueError(
                            f"{file_name} 0x{resource_offset:X}: 仅支持未压缩"
                            f"(0100)资源，实际 {info['resource_type'].hex()}"
                        )
                    resource_raw_cache[resource_offset] = info["raw_data"]
                file_offset = resource_offset + 8 + raw_offset
                original_slot = resource_raw_cache[resource_offset][
                    raw_offset:raw_offset + byte_len
                ]

            if output[file_offset:file_offset + byte_len] != original_slot:
                raise ValueError(
                    f"{record_id}: 目标槽已被改动，无法原地替换"
                )
            if original_slot[-2:] != TERMINATOR:
                raise ValueError(
                    f"{record_id}: 原槽未以FFFF结尾 (byte_len 可能不含终止符)"
                )

            new_slot = _encode_slot(
                character_codes, record["translation"], byte_len, record_id,
                source=record.get("source"),
            )
            output[file_offset:file_offset + byte_len] = new_slot
            string_count += 1

        if len(output) != len(base):
            raise AssertionError(f"{file_name}: 原地替换改变了文件长度")
        replacements[key] = bytes(output)
        file_count += 1

    return file_count, string_count
