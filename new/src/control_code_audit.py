"""Build-time check that a translation never drops a pause control code.

``▽`` (``01FF``) and ``{大停顿}`` (``92FF``) are the engine's wait-for-input and
long-pause markers.  If a translation loses one, the script does not stop: the
dialogue flashes past and runs straight on into whatever command follows, which
in practice walks the player out of the room.  That is exactly what the
computer-room floppy-disk conversation and the fortune teller's "don't read my
fortune" branch did before 2026-07-26, and it is invisible in the JSON -- the
line reads perfectly well, it just never pauses.

Only *losses* are an error.  Translators legitimately add a ``▽`` when a
Chinese line needs to be split into two screens, so a higher count is fine.

Overlay sources keep the raw little-endian notation (``{FF01}``/``{FF92}``)
while translations use the named macros, so both spellings are normalised
before counting.
"""
import json
import re
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
DATA_DIRECTORY = HERE.parent / "data"

# Files whose records carry a source/translation pair.
AUDITED_FILES = (
    "text.json",
    "overlay_text.json",
    "slpm_text.json",
    "f0098_text.json",
)

PAUSE_MARKERS = ("▽", "{大停顿}")

# The extractor writes control codes little-endian, so the same code appears as
# {FF01} in a raw source and as its macro in a translation.
RAW_TO_MACRO = {
    "{FF01}": "▽",
    "{FF92}": "{大停顿}",
}

_TOKEN = re.compile(r"\{[^}]{1,10}\}|▽")


def _normalise(text):
    for raw, macro in RAW_TO_MACRO.items():
        text = text.replace(raw, macro)
    return text


def _counts(text):
    return Counter(
        token for token in _TOKEN.findall(_normalise(text))
        if token in PAUSE_MARKERS
    )


def find_dropped_pause_markers(data_directory=DATA_DIRECTORY):
    """Return [(file, record id, marker, source count, translation count)]."""
    data_directory = Path(data_directory)
    dropped = []

    for file_name in AUDITED_FILES:
        path = data_directory / file_name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for records in data.values():
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                source = record.get("source")
                translation = record.get("translation")
                if (
                    not isinstance(source, str)
                    or not isinstance(translation, str)
                    or not translation
                    or translation == source
                ):
                    continue
                source_counts = _counts(source)
                translation_counts = _counts(translation)
                for marker in PAUSE_MARKERS:
                    wanted = source_counts.get(marker, 0)
                    got = translation_counts.get(marker, 0)
                    if got < wanted:
                        dropped.append((
                            file_name,
                            record.get("id", "<unknown>"),
                            marker,
                            wanted,
                            got,
                        ))
    return dropped


def assert_no_dropped_pause_markers(data_directory=DATA_DIRECTORY):
    dropped = find_dropped_pause_markers(data_directory)
    if not dropped:
        return
    lines = "\n".join(
        f"  {file_name} {record_id}: {marker} {wanted} -> {got}"
        for file_name, record_id, marker, wanted, got in dropped[:20]
    )
    more = "" if len(dropped) <= 20 else f"\n  ... 另有 {len(dropped) - 20} 条"
    raise AssertionError(
        f"{len(dropped)} 条译文丢失了停顿控制符，对话会不停顿地冲过去并"
        f"自动离开场景：\n{lines}{more}"
    )
