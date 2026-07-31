"""Compare the Form-1 files stored in two raw PS1 disc images."""

import argparse
import json
from pathlib import Path

from src.disc_injector import extract_file_from_image


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT / "extrac" / "_iso_manifest.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    differences = []
    skipped = 0

    with arguments.first.open("rb") as first_image:
        with arguments.second.open("rb") as second_image:
            for entry in manifest["entries"]:
                path = entry.get("path")
                if not path:
                    continue
                try:
                    first_data = extract_file_from_image(first_image, entry)
                    second_data = extract_file_from_image(second_image, entry)
                except ValueError as error:
                    if "Form 2 sector is not supported" not in str(error):
                        raise
                    skipped += 1
                    continue
                if first_data == second_data:
                    continue
                changed = sum(
                    before != after
                    for before, after in zip(first_data, second_data)
                )
                differences.append((path, changed, len(first_data)))

    print(f"Different Form-1 files: {len(differences)}")
    for path, changed, size in differences:
        print(f"{path}: {changed} changed byte(s) / {size}")
    print(f"Skipped Form-2 entries: {skipped}")


if __name__ == "__main__":
    main()
