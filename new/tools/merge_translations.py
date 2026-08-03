#!/usr/bin/env python3
"""Merge a translation drop into data/, without losing repairs made since.

The translators work from copies of the data files and send back a directory of
them.  Most of that is a plain adoption, but two things make it worth a tool.

A drop can be stale.  The one on 2026-08-02 carried the same overlay_text.json
that was merged the day before, which by then was missing the 121 wait codes
restored into it -- copying it over would have silently undone that work and put
every appraisal-shop page back to scrolling past.  So overlay_text.json is
compared with its wait codes discounted, and a file that differs only by them is
reported as stale and skipped.

And the fixed-length blocks cannot grow.  A translation that gained a character
has to be caught here rather than at injection time, where the message is about
bytes rather than about which line someone edited.

Run from new/:
    python tools/merge_translations.py data/new_translation
Add --apply to write.  Overlay edits still need restore_overlay_waits.py
afterwards, and this says so when there are any.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from src.text_codec import encode_text, load_character_codes
from tools.restore_overlay_waits import strip_waits

DATA = NEW_DIR / "data"
OVERLAY = "overlay_text.json"
FILES = ("text.json", "slpm_text.json", "f0098_text.json", OVERLAY)


def _records(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {record["id"]: record for record in data}
    return {
        record["id"]: record
        for value in data.values()
        if isinstance(value, list)
        for record in value
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("drop", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()

    character_codes = load_character_codes(DATA / "codetable.json")
    adoptable = []

    for name in FILES:
        incoming_path = arguments.drop / name
        if not incoming_path.is_file():
            print(f"{name}: not in the drop, skipped")
            continue

        ours = _records(DATA / name)
        theirs = _records(incoming_path)
        if set(ours) != set(theirs):
            print(
                f"{name}: record sets differ "
                f"(+{len(set(theirs) - set(ours))} -{len(set(ours) - set(theirs))}), "
                f"skipped"
            )
            continue

        # Anything but the translation is ours to keep: offsets, budgets and
        # the overlay sources repaired against the disc.
        structural = [
            record_id
            for record_id in ours
            if {k: v for k, v in ours[record_id].items() if k != "translation"}
            != {k: v for k, v in theirs[record_id].items() if k != "translation"}
        ]

        # The overlay's waits live in both fields and are re-derived from the
        # disc, so they must not count as a difference either way.
        bare = strip_waits if name == OVERLAY else (lambda text: text or "")
        edited = [
            record_id
            for record_id in ours
            if bare(ours[record_id].get("translation"))
            != bare(theirs[record_id].get("translation"))
        ]

        overlong = []
        for record_id in edited:
            budget = theirs[record_id].get("max_bytes")
            if budget is None:
                continue
            try:
                encoded = encode_text(
                    character_codes, theirs[record_id].get("translation") or ""
                )
            except ValueError:
                continue  # raw control notation; its own injector checks it
            if len(encoded) > budget:
                overlong.append(f"{record_id}(+{len(encoded) - budget})")

        note = ""
        if structural:
            note = f"  ** {len(structural)} record(s) differ outside translation"
        print(f"{name}: {len(edited)} translation edit(s){note}")
        for record_id in edited[:20]:
            print(
                f"    {record_id}\n"
                f"      - {ours[record_id].get('translation')!r}\n"
                f"      + {theirs[record_id].get('translation')!r}"
            )
        if len(edited) > 20:
            print(f"    ... and {len(edited) - 20} more")
        if overlong:
            print(f"    ** does not fit: {' '.join(overlong)}")
        if not edited:
            print("    stale or unchanged; leaving ours in place")
        if edited and not overlong and not structural:
            adoptable.append(name)

    if not arguments.apply:
        print(f"\n(dry run; --apply would copy: {', '.join(adoptable) or 'nothing'})")
        return 0

    for name in adoptable:
        shutil.copyfile(arguments.drop / name, DATA / name)
        print(f"wrote data/{name}")
    if OVERLAY in adoptable:
        print("\nnow run: python tools/restore_overlay_waits.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
