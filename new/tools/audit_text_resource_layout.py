"""Audit translated text resources for unsafe partial string relocation.

The game does not treat every resource as a bag of independent strings.  Some
dialogue readers retain or advance the current record across button presses.
Moving only an overflowing string to the resource tail can therefore make a
page render correctly and then fail on the next input.  This tool simulates
the builder's strict-fixed and allow-growth layouts for every resource and
reports every block whose pointers would be reordered by partial relocation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.text_block_builder import build_text_blocks
from src.text_codec import load_character_codes
from src.text_records import encode_records, load_text_data
from src.text_resource_builder import (
    ALLOW_GROWTH_RESOURCE_KEYS,
    COMPACT_RESOURCE_KEYS,
    FIXED_LAYOUT_RESOURCE_KEYS,
    PASSTHROUGH_RESOURCE_KEYS,
    build_fixed_layout_raw_data,
    pack_text_resource,
    read_resource_info,
)


NEW_DIRECTORY = Path(__file__).resolve().parents[1]
PROJECT_DIRECTORY = NEW_DIRECTORY.parent


def _pointers(raw_data: bytes, count: int) -> list[int]:
    return [
        int.from_bytes(raw_data[index * 4:index * 4 + 4], "little")
        for index in range(count)
    ]


def audit() -> dict:
    character_codes = load_character_codes(NEW_DIRECTORY / "data" / "codetable.json")
    records = encode_records(
        load_text_data(NEW_DIRECTORY / "data" / "text.json"),
        character_codes,
    )
    blocks = build_text_blocks(records)
    source_directory = PROJECT_DIRECTORY / "extrac" / "D"

    growth_candidates = []
    invalid_blocks = []
    resource_count = 0

    for block in blocks:
        if block.get("kind") != "resource":
            continue
        resource_count += 1
        key = (block["file_name"], block["block_offset"])
        if key in PASSTHROUGH_RESOURCE_KEYS or key in FIXED_LAYOUT_RESOURCE_KEYS:
            continue

        source = (source_directory / f"{key[0]}.BIN").read_bytes()
        info = read_resource_info(source, key[1])

        try:
            build_fixed_layout_raw_data(block, info["raw_data"])
            continue
        except (ValueError, KeyError):
            pass

        try:
            grown = build_fixed_layout_raw_data(
                block,
                info["raw_data"],
                allow_growth=True,
            )
            packed = pack_text_resource(grown, info["resource_id"])
        except (ValueError, KeyError) as error:
            invalid_blocks.append({
                "file": key[0],
                "offset": f"0x{key[1]:X}",
                "reason": str(error),
            })
            continue

        if len(packed) > info["total_size"]:
            continue

        count = len(block["records"])
        old_pointers = _pointers(info["raw_data"], count)
        new_pointers = _pointers(grown, count)
        moved_indices = [
            index
            for index, (old, new) in enumerate(zip(old_pointers, new_pointers))
            if old != new
        ]
        if not moved_indices:
            continue

        pointer_reorders = [
            index
            for index in range(count - 1)
            if new_pointers[index] > new_pointers[index + 1]
        ]
        growth_candidates.append({
            "file": key[0],
            "offset": f"0x{key[1]:X}",
            "record_count": count,
            "moved_count": len(moved_indices),
            "moved_records": [
                block["records"][index].get("id", f"record-{index}")
                for index in moved_indices
            ],
            "pointer_reorders_after_records": pointer_reorders,
            "unsafe_pointer_order": bool(pointer_reorders),
            "layout_policy": (
                "allow-growth"
                if key in ALLOW_GROWTH_RESOURCE_KEYS
                else "compact"
            ),
            "forced_compact": (
                key in COMPACT_RESOURCE_KEYS
                or key not in ALLOW_GROWTH_RESOURCE_KEYS
            ),
        })

    return {
        "resource_count": resource_count,
        "growth_candidate_count": len(growth_candidates),
        "unsafe_pointer_order_count": sum(
            item["unsafe_pointer_order"] for item in growth_candidates
        ),
        "growth_candidates": growth_candidates,
        "invalid_blocks": invalid_blocks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = audit()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")
    if args.summary:
        policies = {}
        for item in result["growth_candidates"]:
            policy = item["layout_policy"]
            policies[policy] = policies.get(policy, 0) + 1
        print(
            f"resources={result['resource_count']} "
            f"partial-relocation-candidates={result['growth_candidate_count']} "
            f"reordered={result['unsafe_pointer_order_count']} "
            f"policies={policies} "
            f"invalid={len(result['invalid_blocks'])}"
        )
    else:
        print(rendered)


if __name__ == "__main__":
    main()
