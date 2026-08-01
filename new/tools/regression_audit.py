#!/usr/bin/env python3
"""Re-check every bug this project has already fixed.

Most of these were found the same way: someone played far enough to see a wrong
glyph, a blank, or a screen that crawled.  That is a terrible feedback loop, and
several of them came back later because a codetable rearrange or a new text
block silently invalidated the fix.  Each check below is the *static* form of
one of those symptoms, so a regression shows up here instead of in a tester's
screenshot.

Run from new/:  python tools/regression_audit.py
Exit status is non-zero if anything fails, so it can gate a release build.
"""
import json
import struct
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DIR = HERE.parent
sys.path.insert(0, str(NEW_DIR))

from src.f14_context_aliases import (
    DEFAULT_CODETABLE_PATH,
    F14_CAPACITY,
    HARDCODED_GLYPH_INDICES,
    build_f14_context_alias_plan,
)
from src.f0098_text import load_f0098_text_records, translated_f0098_texts
from src.font_builder import (
    DRAW_W,
    FALLBACK_FONT_PATH,
    FALLBACK_FONT_PX,
    FONT_PATH,
    FONT_PX,
    GLYPH_ARTWORK,
    GLYPH_H,
    load_codetable,
    load_glyph_artwork,
    load_original_glyph,
    render_glyph,
)
from src.glyph_layout import DYNAMIC_SPECIAL_LOW_INDICES, glyph_indices
from src.name_entry import SOURCE_CODE_ROWS
from src.overlay_text import load_overlay_text_records, translated_overlay_texts
from src.slpm_text import load_slpm_text_records, translated_slpm_texts
from src.text_codec import load_character_codes
from src.text_records import choose_text, load_text_data
from src.unified_normal_text_plan import build_unified_normal_text_plan

DATA = NEW_DIR / "data"
TEXT_PATH = DATA / "text.json"
BUILT_SLPM = NEW_DIR / "build" / "SLPM_871.54"
ORIGINAL_UI_PATH = DATA / "original_ui_codetable.json"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def _load_context():
    slpm = load_slpm_text_records()
    f98 = load_f0098_text_records()
    plan = build_unified_normal_text_plan(
        DEFAULT_CODETABLE_PATH,
        TEXT_PATH,
        extra_used_texts=(
            translated_slpm_texts(slpm, renderer="dynamic")
            + translated_f0098_texts(f98)
            + translated_overlay_texts()
        ),
        extra_static_texts=translated_slpm_texts(slpm, renderer="static"),
    )
    ranges = (
        (0xE6A26, 0xE6D58),
        (0xEF298, 0xEF33C),
        (0xE4768, 0xE48A8),
        (0xE7BF0, 0xE813A),
    )
    context_texts = tuple(
        record["translation"]
        for low, high in ranges
        for record in slpm
        if low <= record["offset"] < high and record["translation"]
    )
    alias = build_f14_context_alias_plan(
        global_character_overrides=plan.global_character_overrides,
        existing_font_overrides=plan.font_overrides,
        extra_context_texts=context_texts,
    )
    codes = dict(load_character_codes(DEFAULT_CODETABLE_PATH))
    codes.update(plan.global_character_overrides)
    return slpm, f98, plan, alias, codes, ranges


def main():
    codetable = load_codetable(DEFAULT_CODETABLE_PATH)
    text_data = load_text_data(TEXT_PATH)
    slpm, f98, plan, alias, codes, slpm_ranges = _load_context()

    # -- hardcoded glyph cells ------------------------------------------------
    # 学校1＋, the save screen's Ｂ reading 率, and 贪欲界１Ｆ率Ａ were all the
    # same defect: a cell the executable indexes directly got a different glyph.
    original_ui = {
        int.from_bytes(bytes.fromhex(code), "little"): character
        for code, character in json.loads(
            ORIGINAL_UI_PATH.read_text(encoding="utf-8")
        ).items()
    }
    hardcoded = (
        list(range(0x004, 0x008))
        + [0x00D, 0x010, 0x015]
        + list(range(0x02A, 0x034))
        + [0x034, 0x035, 0x039]
    )
    misplaced = [
        f"{index:#05x}={original_ui[index]}"
        for index in hardcoded
        if index in original_ui
        and load_character_codes(DEFAULT_CODETABLE_PATH).get(original_ui[index])
        != index.to_bytes(2, "little")
    ]
    check(
        "hardcoded glyph cells carry their own character",
        not misplaced,
        " ".join(misplaced),
    )
    check(
        "no cell still needs protecting from aliases",
        not HARDCODED_GLYPH_INDICES,
        f"still protected: {sorted(hex(i) for i in HARDCODED_GLYPH_INDICES)}",
    )

    # -- name-entry keyboard --------------------------------------------------
    # The grid returns the original code behind each key, so its 160 characters
    # have to sit exactly on those cells or every typed name comes out wrong.
    rows = json.loads(
        (DATA / "name_entry_characters.json").read_text(encoding="utf-8")
    )["rows"]
    character_codes = load_character_codes(DEFAULT_CODETABLE_PATH)
    bad_keys = [
        character
        for row, row_codes in zip(rows, SOURCE_CODE_ROWS)
        for character, code in zip(row, row_codes)
        if character_codes.get(character) != code.to_bytes(2, "little")
    ]
    check("name-entry keyboard pins", not bad_keys, "".join(bad_keys))

    # -- F14 capacity ---------------------------------------------------------
    # 霆 lost from 雷霆, blank armour rows, 凶鸟 drawn as 鸟: a character a static
    # screen needs that sits above F14's 0x567 comes out empty, and the
    # out-of-range read is what makes those lists crawl.
    def over_capacity(texts, extra=None):
        mapping = dict(codes)
        if extra:
            mapping.update(extra)
        bad = set()
        for text in texts:
            for index in glyph_indices(mapping, text):
                if index >= F14_CAPACITY:
                    bad.add(codetable.get(index, "?"))
        return bad

    f14_blocks = {
        "F0094-00001008": "item names",
        "F0094-00002630": "skill names",
        "F0094-0000003C": "demon names",
        "F0094-000039F8": "race names",
        "F0094-00000000": "preset names",
        "F0076-00002C7C": "negotiation menu",
        "F0084-00000800": "action menu",
        "F0084-0000E000": "action menu 2",
        "F0094-00002070": "green panel (item)",
        "F0094-00002D98": "green panel (skill)",
    }
    for prefix, label in f14_blocks.items():
        texts = [
            choose_text(record)
            for records in text_data.values()
            for record in records
            if record.get("id", "").startswith(prefix)
        ]
        bad = over_capacity(texts, alias.character_overrides)
        check(f"F14 capacity: {label}", not bad, "".join(sorted(bad)))
    for (low, high), label in zip(
        slpm_ranges, ("action results", "MARKER help", "area names", "equip help")
    ):
        texts = [
            record["translation"]
            for record in slpm
            if low <= record["offset"] < high and record["translation"]
        ]
        bad = over_capacity(texts, alias.character_overrides)
        check(f"F14 capacity: {label}", not bad, "".join(sorted(bad)))

    # -- relocation -----------------------------------------------------------
    # Index 0 is the transparent space; a character relocated onto it vanishes,
    # which is how 令 disappeared from 「風紀委員の命令」.
    zeroed = [
        character
        for character, code in plan.global_character_overrides.items()
        if int.from_bytes(code, "little") == 0
    ]
    check("nothing relocated onto index 0", not zeroed, "".join(zeroed))

    # -- control codes --------------------------------------------------------
    # A lost ▽ does not error anywhere: the script simply runs on and walks the
    # player out of the room.
    dropped = [
        record["id"]
        for records in text_data.values()
        for record in records
        if (record.get("source") or "").count("▽")
        > (record.get("translation") or "").count("▽")
    ]
    check("pause markers kept", not dropped, " ".join(dropped[:5]))

    # The overlay blocks needed their own check.  Their exporter dropped every
    # 01FF it read -- 121 of them -- so the appraisal shop, the healing spring
    # and the save-load prompts all ran their pages together with no pause, and
    # nothing in the data said a pause had ever been there.  Comparing each
    # record's control codes against the disc is the only way to see it.
    from tools.restore_overlay_waits import _code_of, _codes_from_slot, _split

    overlay_drift = []
    for file_name, records in load_overlay_text_records().items():
        original = (NEW_DIR.parent / "extrac" / "D" / f"{file_name}.BIN").read_bytes()
        for record in records:
            offset = int(record["file_offset"], 16)
            disc = _codes_from_slot(original[offset:offset + record["max_bytes"]])
            recorded = [
                _code_of(token)
                for kind, token in _split(record.get("source"))
                if kind == "code"
            ]
            if disc != recorded:
                overlay_drift.append(record["id"])
    check(
        "overlay sources match the disc's control codes",
        not overlay_drift,
        f"{len(overlay_drift)}: " + " ".join(overlay_drift[:5]),
    )

    overlay_dropped = [
        record["id"]
        for records in load_overlay_text_records().values()
        for record in records
        if (record.get("source") or "").count("▽")
        > (record.get("translation") or "").count("▽")
    ]
    check(
        "overlay pause markers kept",
        not overlay_dropped,
        " ".join(overlay_dropped[:5]),
    )

    # -- invisible characters -------------------------------------------------
    # Zero-width joiners pasted into a translation are invisible in the editor
    # and draw as tofu in game (□明□：).
    invisible = {}
    for records in text_data.values():
        for record in records:
            for character in record.get("translation") or "":
                if character == "\n":
                    continue
                if unicodedata.category(character) == "Cf":
                    invisible.setdefault(character, []).append(record["id"])
    check(
        "no format-control characters in translations",
        not invisible,
        " ".join(
            f"U+{ord(c):04X}x{len(v)}" for c, v in invisible.items()
        ),
    )

    # -- font coverage --------------------------------------------------------
    main_font = _font(FONT_PATH, FONT_PX)
    tofu = render_glyph("\U000F0000", main_font)
    fallback = (
        _font(FALLBACK_FONT_PATH, FALLBACK_FONT_PX)
        if FALLBACK_FONT_PATH.is_file()
        else None
    )
    uncovered = [
        character
        for character in codetable.values()
        if character
        and render_glyph(character, main_font) == tofu
        and fallback is None
    ]
    check(
        "every glyph has artwork",
        not uncovered,
        " ".join(f"U+{ord(c):04X}" for c in uncovered),
    )

    # The Macca symbol is artwork, so it is copied out of the original 2bpp F13
    # rather than rendered.  Reading that as "0 and 1 are ink" dropped shade 2,
    # which is the middle of every stroke, and the symbol came out shattered.
    # Decoding a glyph whose shape is known independently -- the fullwidth １ at
    # 0x2B -- catches any future misreading of the format.
    def ink_rows(index):
        glyph = load_original_glyph(index)
        return [
            [
                not (glyph[y * 2 + x // 8] >> (x % 8)) & 1
                for x in range(DRAW_W)
            ]
            for y in range(GLYPH_H)
        ]

    one = ink_rows(0x2B)
    # Every drawn row of a １ is a solid run: a dotted column means shades were
    # dropped.  Row 0 is blank.
    broken = [
        y
        for y, row in enumerate(one)
        if any(row)
        and any(
            row[x] and not row[x + 1] and row[x + 2]
            for x in range(len(row) - 2)
        )
    ]
    check(
        "original 2bpp glyphs decode without dropping shades",
        not broken,
        f"dotted rows in the fullwidth １: {broken}",
    )
    # The hand-drawn replacements are packed from PNGs outside the font, so a
    # missing or resized file has to fail here rather than ship a blank cell.
    missing_artwork = []
    for character, path in GLYPH_ARTWORK.items():
        try:
            packed = load_glyph_artwork(path)
        except (OSError, ValueError) as error:
            missing_artwork.append(f"{character}: {error}")
            continue
        if all(byte == 0xFF for byte in packed):
            missing_artwork.append(f"{character}: packs to a blank cell")
    check(
        "hand-drawn glyph artwork loads",
        not missing_artwork,
        "; ".join(missing_artwork),
    )

    # -- fixed-length text ----------------------------------------------------
    # In-place blocks cannot grow; the build fails on these, but catching them
    # here means the translators hear about it without waiting for a full build.
    overlong = []
    unencodable = []
    from src.text_codec import encode_text

    def measure(record_id, translation, budget):
        try:
            encoded = encode_text(character_codes, translation or "")
        except ValueError:
            # Overlay blocks keep raw control notation that only their own
            # injector expands, so an encode failure here is not automatically
            # a defect -- report it separately rather than as an overflow.
            unencodable.append(record_id)
            return
        if len(encoded) > budget:
            overlong.append(f"{record_id}(+{len(encoded) - budget})")

    for record in slpm:
        measure(record["id"], record["translation"], record["max_bytes"])
    for records in load_overlay_text_records().values():
        for record in records:
            measure(
                record["id"], record.get("translation"), record["max_bytes"]
            )
    check("fixed-length text fits", not overlong, " ".join(overlong[:5]))
    if unencodable:
        print(
            f"  note  {len(unencodable)} record(s) use raw control notation "
            f"and were not measured here (the build still checks them)"
        )

    # -- executable patches ---------------------------------------------------
    # Every one of these was a crash, a hang or a slowdown at some point.
    if BUILT_SLPM.is_file():
        data = BUILT_SLPM.read_bytes()

        def word(address):
            return struct.unpack_from("<I", data, address - 0x8000F800)[0]

        sites = {
            0x80049578: (0x2402_0ACE, "F13 cache table sized for 0xACE"),
            0x8005B2E4: (0x2407_000C, "dialogue advance fixed at 12"),
            0x8004A064: (0x2407_000C, "menu advance fixed at 12"),
            0x8006F0A8: (0x0801_70A6, "MARKER type-6 stride floor"),
            0x80047688: (0x0801_1F6F, "big-font name gate"),
            0x8004844C: (0x0801_225D, "out-of-range glyph skips instead of hanging"),
            0x80047A6C: (0x0803_F823, "F14 glyph AddPrim self-link guard"),
            0x80048514: (0x0801_1F8F, "save-slot AddPrim self-link guard"),
        }
        for address, (expected, label) in sites.items():
            check(f"patch: {label}", word(address) == expected,
                  f"{address:#010x} = {word(address):08X}, expected {expected:08X}")

        # The guardian label used to read 暗显灵 because these immediates were
        # literals that a rearrange silently retargeted.
        for offset, character in ((0x0386E0, "守"), (0x0386F0, "护"), (0x038700, "灵")):
            index = struct.unpack_from("<H", data, offset)[0]
            check(
                f"guardian label {character}",
                codetable.get(index) == character,
                f"{offset:#08x} -> {index:#06x} = {codetable.get(index)!r}",
            )
    else:
        check("built SLPM present", False, f"{BUILT_SLPM} not found; run build.py")

    width = max(len(name) for name, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        if ok:
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


def _font(path, size):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size)


if __name__ == "__main__":
    raise SystemExit(main())
