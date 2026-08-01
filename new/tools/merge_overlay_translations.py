#!/usr/bin/env python3
"""Take a translation pass back from the translators without losing our fixes.

The translators work from a copy of ``overlay_text.json`` and return it with
edited ``translation`` fields.  Merging that back is not a plain copy, because
the file they were given is missing things we have since repaired: the 121 wait
codes the exporter dropped, and the two slots where glyph 0x03FF (店) had been
mis-decoded as a line break.  Copying their file over ours would undo all of it.

Rather than diff three files, this keeps our ``source`` fields -- which are now
the disc's own truth -- and re-derives every wait from the disc afterwards.  The
restoration is idempotent and driven entirely by the original bytes, so adopting
their text wholesale and re-running it lands on the right answer whether they
edited a record or not.

Run from new/:
    python tools/merge_overlay_translations.py data/overlay_text——new.json
Add --apply to write; without it, nothing is touched.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from tools.restore_overlay_waits import (
    GLYPH_FIXES,
    OVERLAY_PATH,
    TRIMS,
    WAIT_MACRO,
)

# Translations we override on purpose: five trimmed by one character to make
# room for a restored wait, and one repaired after 店 was exported as a line
# break.  Adopting the incoming text for these would just be undone by
# restore_overlay_waits, so hold them and say so.
HELD = set(TRIMS) | {
    record_id
    for record_id, fields in GLYPH_FIXES.items()
    if "translation" in fields
}


def _bare(text):
    """The text alone, with the waits this tool re-derives stripped out."""
    return (text or "").replace(WAIT_MACRO, "")


def _by_id(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data, {
        record["id"]: record for records in data.values() for record in records
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("incoming", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()

    ours_data, ours = _by_id(OVERLAY_PATH)
    _, theirs = _by_id(arguments.incoming)

    missing = sorted(set(ours) - set(theirs))
    added = sorted(set(theirs) - set(ours))
    if missing or added:
        raise SystemExit(
            f"record sets differ: {len(missing)} missing, {len(added)} added "
            f"({(missing + added)[:3]})"
        )

    # Translators are not supposed to touch these, so anything left after
    # discounting the waits and the two hand-repaired glyph slots means they
    # were working from a file older than our source repairs.
    edited_sources = [
        record_id
        for record_id in ours
        if record_id not in GLYPH_FIXES
        and _bare(theirs[record_id].get("source"))
        != _bare(ours[record_id].get("source"))
    ]

    adopted = []
    held = []
    for record_id, record in ours.items():
        incoming = theirs[record_id].get("translation")
        if _bare(record.get("translation")) == _bare(incoming):
            continue
        if record_id in HELD:
            held.append(record_id)
            continue
        adopted.append(record_id)
        record["translation"] = incoming

    print(f"{len(adopted)} translation(s) adopted")
    for record_id in adopted:
        print(f"  {record_id}")
    if held:
        print(f"\n{len(held)} held at our version (see restore_overlay_waits):")
        for record_id in held:
            print(f"  {record_id}: {ours[record_id]['translation']!r}")
    if edited_sources:
        print(
            f"\n{len(edited_sources)} source field(s) differ beyond the wait "
            f"codes -- check these by hand:"
        )
        for record_id in edited_sources:
            print(f"  {record_id}")

    if not arguments.apply:
        print("\n(dry run; pass --apply to write, then re-run "
              "restore_overlay_waits.py --apply)")
        return 0

    OVERLAY_PATH.write_text(
        json.dumps(ours_data, ensure_ascii=False, indent=1),
        encoding="utf-8",
        newline="\r\n",
    )
    print(f"\nwrote {OVERLAY_PATH}")
    print("now run: python tools/restore_overlay_waits.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
