from pathlib import Path

from src.text_block_builder import build_text_blocks
from src.text_codec import load_character_codes
from src.text_file_builder import rebuild_text_files
from src.text_records import encode_records, load_text_data
from src.text_resource_builder import (
    PASSTHROUGH_RESOURCE_KEYS,
    build_text_resources,
)


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
PROJECT_DIRECTORY = NEW_DIRECTORY.parent

DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"
DEFAULT_TEXT_PATH = NEW_DIRECTORY / "data" / "text.json"
DEFAULT_SOURCE_DIRECTORY = PROJECT_DIRECTORY / "extrac" / "D"


def build_text_files(
    text_path=DEFAULT_TEXT_PATH,
    codetable_path=DEFAULT_CODETABLE_PATH,
    source_directory=DEFAULT_SOURCE_DIRECTORY,
    character_code_overrides=None,
    section_character_code_overrides=None,
    record_character_code_overrides=None,
):
    character_codes = load_character_codes(codetable_path)
    if character_code_overrides:
        character_codes.update(character_code_overrides)

    section_character_codes = {}
    for section, overrides in (section_character_code_overrides or {}).items():
        section_codes = dict(character_codes)
        section_codes.update(overrides)
        section_character_codes[section] = section_codes

    text_data = load_text_data(text_path)
    encoded_records = encode_records(
        text_data,
        character_codes,
        section_character_codes=section_character_codes,
        record_character_code_overrides=(
            record_character_code_overrides
        ),
    )
    text_blocks = build_text_blocks(encoded_records)
    passthrough_blocks = [
        block
        for block in text_blocks
        if (block["file_name"], block["block_offset"])
        in PASSTHROUGH_RESOURCE_KEYS
    ]
    text_resources = build_text_resources(text_blocks, source_directory)
    rebuilt_files = rebuild_text_files(
        text_blocks,
        text_resources,
        source_directory,
    )

    return {
        "encoded_records": encoded_records,
        "text_blocks": text_blocks,
        "text_resources": text_resources,
        "passthrough_blocks": passthrough_blocks,
        "rebuilt_files": rebuilt_files,
    }


def create_disc_replacements(build_result):
    rebuilt_files = build_result.get("rebuilt_files")
    if not isinstance(rebuilt_files, list):
        raise ValueError("build_result缺少rebuilt_files")

    return {
        f"D/{file_info['file_name']}.BIN": file_info["data"]
        for file_info in rebuilt_files
    }



def summarize_text_build(build_result):
    encoded_records = build_result["encoded_records"]
    text_blocks = build_result["text_blocks"]
    text_resources = build_result["text_resources"]
    passthrough_blocks = build_result.get("passthrough_blocks", [])
    rebuilt_files = build_result["rebuilt_files"]

    return {
        "record_count": len(encoded_records),
        "block_count": len(text_blocks),
        "resource_count": len(text_resources),
        "passthrough_resource_count": len(passthrough_blocks),
        "passthrough_record_count": sum(
            block["record_count"] for block in passthrough_blocks
        ),
        "static_block_count": sum(
            block["kind"] == "static" for block in text_blocks
        ),
        "file_count": len(rebuilt_files),
        "raw_text_size": sum(
            len(block["data"]) for block in text_blocks
        ),
        "packed_resource_size": sum(
            resource["resource_size"] for resource in text_resources
        ),
    }
