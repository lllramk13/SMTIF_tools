#!/usr/bin/env python3
"""Put the wait-for-input codes the overlay exporter dropped back into the data.

``01FF`` (``▽``) is the code that stops a message until the player presses a
button.  The original F0049/F0051/F0052 slots are full of them, but none reached
``data/overlay_text.json``: its ``source`` fields were exported without them, so
the translators never saw a page break to preserve and every one of those
messages now scrolls past instead of waiting.  The appraisal shop's explanation
alone lost five.

Apart from two slots handled by name below, this is the only code the exporter
lost, so the original and the recorded sequences line up unambiguously: strip
every ``01FF`` from the disc's sequence and what remains is exactly what the JSON
holds.  Each missing code therefore belongs at a known point, which
``_insert_waits`` locates by the page clear that follows it.

Run from new/:  python tools/restore_overlay_waits.py [--apply]
Without --apply it only reports.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from src.text_codec import CONTROL_CODES, load_character_codes, encode_text

OVERLAY_PATH = NEW_DIR / "data" / "overlay_text.json"
REPORT_PATH = NEW_DIR / "build" / "overlay_wait_restore.txt"
SOURCE_DIRECTORY = NEW_DIR.parent / "extrac" / "D"
WAIT_CODE = "01FF"
WAIT_MACRO = "▽"
PAGE_CODE = "02FF"

_MACROS = sorted(CONTROL_CODES, key=len, reverse=True)
_TOKEN = re.compile(
    "|".join(re.escape(macro) for macro in _MACROS) + r"|\{[0-9A-Fa-f]{4}\}"
)


def _code_of(token):
    if token in CONTROL_CODES:
        return CONTROL_CODES[token].upper()
    inner = token[1:-1].upper()
    # Sources spell a raw code big-endian ({FF01}); the codec spells it the way
    # the bytes actually run ({01FF}).
    return inner if inner.endswith("FF") else inner[2:] + inner[:2]


def _split(text):
    """Split into alternating literal runs and control tokens."""
    parts = []
    position = 0
    for match in _TOKEN.finditer(text or ""):
        if match.start() > position:
            parts.append(("text", text[position:match.start()]))
        parts.append(("code", match.group()))
        position = match.end()
    if text and position < len(text):
        parts.append(("text", text[position:]))
    return parts


def _codes_from_slot(data):
    codes = []
    for offset in range(0, len(data) - 1, 2):
        word = data[offset:offset + 2]
        if word == b"\xFF\xFF":
            break
        if word[1] == 0xFF:
            codes.append(f"{word[0]:02X}FF")
    return codes


def strip_waits(text):
    """``text`` without its wait codes, in either notation.

    Translations spell a wait ``▽``; the exported sources spell the same code
    ``{FF01}``.  Both have to go, so this drops tokens by the code they mean
    rather than by how they are written.
    """
    return "".join(
        value
        for kind, value in _split(text)
        if not (kind == "code" and _code_of(value) == WAIT_CODE)
    )


def _insert_waits(text, disc_codes):
    """Rebuild ``text`` with the dropped waits restored.

    Every wait on the disc sits in one of two places: 124 of the 133 immediately
    before the terminator, the other 8 immediately before a page clear.  So each
    one is identified by *which* page clear follows it, and restoring it means
    inserting a wait before that same page clear here.

    Anchoring on page clears rather than walking the token stream is what makes
    this work on translations too.  Several of them merge two Japanese lines into
    one, so their line-break counts do not match the original's -- but no
    translation adds or drops a page clear, since that is where the text was
    split into screens to begin with.
    """
    before_page = set()
    trailing = 0
    pages_seen = 0
    for position, code in enumerate(disc_codes):
        if code == PAGE_CODE:
            pages_seen += 1
            continue
        if code != WAIT_CODE:
            continue
        following = disc_codes[position + 1] if position + 1 < len(disc_codes) else None
        if following == PAGE_CODE:
            before_page.add(pages_seen)
        else:
            # One slot ends on two waits in a row -- two button presses.
            trailing += 1

    rebuilt = []
    pages_seen = 0
    for kind, value in _split(text):
        if kind == "code" and _code_of(value) == PAGE_CODE:
            if pages_seen in before_page:
                rebuilt.append(WAIT_MACRO)
            pages_seen += 1
        rebuilt.append(value)
    if max(before_page, default=-1) >= pages_seen:
        raise ValueError(
            f"text has {pages_seen} page clear(s), but a wait belongs before "
            f"page {max(before_page)}"
        )
    result = "".join(rebuilt)
    already = len(result) - len(result.rstrip(WAIT_MACRO))
    return result + WAIT_MACRO * max(0, trailing - already)


# Two separate exporter defects, both fixed by hand because each needs a
# judgement call rather than a rule.
#
# Glyph 0x03FF is 店.  Stored little-endian it reads ``FF 03``, and the exporter
# decoded that as the newline control code, so both slots that use the word
# reached the translators as a line break.  「もう店はたたんじまったよ」 became
# 「もう\nはたたんじまったよ」 and the shop-exit menu entry 「店を出る」 became
# 「\nを出る」 -- which is why its translation ends in a stray newline.
#
# Every replacement below names the text it expects to find, so a second run is
# a no-op and an edit made upstream is reported instead of silently reverted.
GLYPH_FIXES = {
    "F0049-00009A14": {
        "source": ("\nを出る", "店を出る"),
        "translation": ("离开\n", "离开商店"),
    },
    "F0049-00009B38": {
        "source": (
            "鑑定屋：もう\nはたたんじまったよ{FF03}帰ってくれないか！",
            "鑑定屋：もう店はたたんじまったよ{FF03}帰ってくれないか！",
        ),
    },
}

# Five slots were translated to exactly their byte budget, so restoring the wait
# leaves no room.  Each loses one character; the meaning is unchanged.
TRIMS = {
    "F0049-00008714": ("多谢惠顾！", "多谢惠顾"),
    "F0049-00008A52": ("没有能收购的东西哟～！", "没有能收购的东西！"),
    "F0049-00008E4C": ("只有满月时才能寻找宝石！", "只有满月才能找宝石！"),
    "F0049-0000936E": ("那就再见啦！", "那就再见！"),
    "F0049-0000990C": (
        "※※※※※※※大家恢复健康了～！",
        "※※※※※※※大家恢复健康了！",
    ),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()

    data = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    character_codes = load_character_codes(NEW_DIR / "data" / "codetable.json")

    stale = []

    def substitute(record, field, expected, replacement):
        # Ignore trailing waits so a field already restored below still counts
        # as done rather than as an upstream edit.
        if (record.get(field) or "").rstrip(WAIT_MACRO) == replacement.rstrip(
            WAIT_MACRO
        ):
            return
        if record.get(field) != expected:
            stale.append(f"{record['id']}.{field}")
            return
        record[field] = replacement

    for records in data.values():
        for record in records:
            for field, (expected, replacement) in GLYPH_FIXES.get(
                record["id"], {}
            ).items():
                substitute(record, field, expected, replacement)
            if record["id"] in TRIMS:
                substitute(record, "translation", *TRIMS[record["id"]])

    report = []
    changed = 0
    skipped = []
    overflow = []
    for file_name, records in data.items():
        slot_source = (SOURCE_DIRECTORY / f"{file_name}.BIN").read_bytes()
        for record in records:
            offset = int(record["file_offset"], 16)
            disc_codes = _codes_from_slot(
                slot_source[offset:offset + record["max_bytes"]]
            )
            if WAIT_CODE not in disc_codes:
                continue
            # Work from the text with its waits removed, so a record is treated
            # the same whether it has never been restored, is already restored,
            # or -- after a translation merge -- has a restored source beside a
            # translation that came back without them.
            bare_source = strip_waits(record.get("source"))
            bare_translation = strip_waits(record.get("translation"))
            recorded = [
                _code_of(token)
                for kind, token in _split(bare_source)
                if kind == "code"
            ]
            if [c for c in disc_codes if c != WAIT_CODE] != recorded:
                skipped.append((record["id"], disc_codes, recorded))
                continue

            # Leave a field alone when its codes already match the disc, so a
            # source that spells its waits ``{FF01}`` keeps that notation
            # instead of being rewritten to ``▽`` for no gain.
            source_codes = [
                _code_of(token)
                for kind, token in _split(record.get("source"))
                if kind == "code"
            ]
            new_source = (
                record.get("source")
                if source_codes == disc_codes
                else _insert_waits(bare_source, disc_codes)
            )
            translation_waits = sum(
                kind == "code" and _code_of(token) == WAIT_CODE
                for kind, token in _split(record.get("translation"))
            )
            new_translation = (
                record.get("translation")
                if translation_waits == disc_codes.count(WAIT_CODE)
                else _insert_waits(bare_translation, disc_codes)
            )
            if (
                new_source == record.get("source")
                and new_translation == record.get("translation")
            ):
                continue
            rebuilt_codes = [
                _code_of(token)
                for kind, token in _split(new_source)
                if kind == "code"
            ]
            if rebuilt_codes != disc_codes:
                raise AssertionError(
                    f"{record['id']}: rebuilt {rebuilt_codes} != disc {disc_codes}"
                )

            encoded = encode_text(character_codes, new_translation)
            if len(encoded) > record["max_bytes"]:
                overflow.append(
                    (record["id"], len(encoded), record["max_bytes"])
                )
                continue

            report.append(f"  {record['id']}  +{disc_codes.count(WAIT_CODE)} 个 ▽")
            report.append(f"    src {record.get('source')!r}")
            report.append(f"    ->  {new_source!r}")
            report.append(f"    dst {record.get('translation')!r}")
            report.append(f"    ->  {new_translation!r}")
            record["source"] = new_source
            record["translation"] = new_translation
            changed += 1

    REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"report -> {REPORT_PATH}")
    print(f"\n{changed} record(s) would gain a wait code")
    if overflow:
        print(f"{len(overflow)} record(s) no longer fit and were left alone:")
        for record_id, needed, budget in overflow:
            print(f"  {record_id}: {needed} > {budget}")
    if stale:
        print(f"{len(stale)} hand-fixed field(s) no longer match; not touched:")
        for name in stale:
            print(f"  {name}")
    if skipped:
        print(f"{len(skipped)} record(s) could not be aligned:")
        for record_id, disc, recorded in skipped:
            print(f"  {record_id}: disc {disc} vs json {recorded}")

    if arguments.apply and changed:
        # Match the file exactly as the exporter wrote it -- one-space indent,
        # CRLF, no trailing newline -- so the diff shows only the text that
        # changed.
        OVERLAY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=1),
            encoding="utf-8",
            newline="\r\n",
        )
        print(f"\nwrote {OVERLAY_PATH}")
    elif changed:
        print("\n(dry run; pass --apply to write)")


if __name__ == "__main__":
    raise SystemExit(main())
