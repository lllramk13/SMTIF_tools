"""Print each F14 context alias beside the globally released glyph it hides."""

from build import NEW_DIRECTORY
from src.f0098_text import (
    load_f0098_text_records,
    translated_f0098_texts,
)
from src.f14_context_aliases import build_f14_context_alias_plan
from src.font_builder import load_codetable
from src.overlay_text import translated_overlay_texts
from src.slpm_text import load_slpm_text_records, translated_slpm_texts
from src.unified_normal_text_plan import build_unified_normal_text_plan


def main():
    slpm_records = load_slpm_text_records()
    f0098_records = load_f0098_text_records()
    normal_plan = build_unified_normal_text_plan(
        NEW_DIRECTORY / "data" / "codetable.json",
        NEW_DIRECTORY / "data" / "text.json",
        extra_used_texts=(
            translated_slpm_texts(slpm_records, renderer="dynamic")
            + translated_f0098_texts(f0098_records)
            + translated_overlay_texts()
        ),
        extra_static_texts=translated_slpm_texts(
            slpm_records,
            renderer="static",
        ),
    )
    action_result_texts = tuple(
        record["translation"]
        for record in slpm_records
        if (
            0xE6A26 <= record["offset"] < 0xE6D58
            and record["translation"]
        )
    )
    alias_plan = build_f14_context_alias_plan(
        text_path=NEW_DIRECTORY / "data" / "text.json",
        codetable_path=NEW_DIRECTORY / "data" / "codetable.json",
        global_character_overrides=normal_plan.global_character_overrides,
        existing_font_overrides=normal_plan.font_overrides,
        extra_context_texts=(
            action_result_texts
            + translated_f0098_texts(f0098_records, renderer="static")
        ),
    )
    original_glyphs = load_codetable()

    print(f"Aliases: {len(alias_plan.aliases)}")
    for alias in alias_plan.aliases:
        index = alias["f14_code"]
        print(
            f"{index:03X}  "
            f"{original_glyphs[index]} -> {alias['character']}"
        )


if __name__ == "__main__":
    main()
