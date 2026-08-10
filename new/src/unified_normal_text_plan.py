from dataclasses import dataclass

from src.font_builder import load_codetable
from src.glyph_layout import (
    DYNAMIC_SPECIAL_LOW_INDICES,
    ORIGINAL_MAX_GLYPH_INDEX,
    STATIC_TEXT_SECTIONS,
    glyph_indices,
)
from src.mixed_name_layout import (
    ORIGINAL_FULLWIDTH_LATIN_INDICES,
    SHARED_GLYPH_CHARACTERS,
    build_mixed_name_global_overrides,
    released_f14_context_alias_indices,
)
from src.text_codec import load_character_codes
from src.text_records import choose_text, load_text_data


EXPANDED_GLYPH_COUNT = 0x0ACE


@dataclass(frozen=True)
class UnifiedNormalTextPlan:
    global_character_overrides: dict[str, bytes]
    section_character_overrides: dict[str, dict[str, bytes]]
    font_overrides: dict[int, str]
    used_indices: frozenset[int]
    static_indices: frozenset[int]
    aliases: tuple[dict, ...]
    highest_index: int


def build_unified_normal_text_plan(
    codetable_path,
    text_path,
    extra_used_texts=(),
    extra_static_texts=(),
):
    codetable = load_codetable(codetable_path)
    character_codes = load_character_codes(codetable_path)
    text_data = load_text_data(text_path)

    used_indices = set()
    static_indices = set()
    for section, records in text_data.items():
        for record in records:
            indices = glyph_indices(character_codes, choose_text(record))
            used_indices.update(indices)
            if section in STATIC_TEXT_SECTIONS:
                static_indices.update(indices)

    for text in extra_used_texts:
        if not isinstance(text, str) or not text:
            raise ValueError("extra used text must be a non-empty string")
        used_indices.update(glyph_indices(character_codes, text))

    for text in extra_static_texts:
        if not isinstance(text, str) or not text:
            raise ValueError("extra static text must be a non-empty string")
        indices = glyph_indices(character_codes, text)
        used_indices.update(indices)
        static_indices.update(indices)

    reserved = set(DYNAMIC_SPECIAL_LOW_INDICES)
    static_targets = sorted(
        (static_indices & reserved)
        | {
            index
            for index in static_indices
            if index > ORIGINAL_MAX_GLYPH_INDEX
        }
    )

    low_range = set(range(1, ORIGINAL_MAX_GLYPH_INDEX + 1))
    direct_free = sorted(low_range - used_indices - reserved, reverse=True)
    displaced_candidates = sorted(
        low_range - static_indices - reserved - set(direct_free),
        reverse=True,
    )
    alias_indices = (
        direct_free[:len(static_targets)]
        + displaced_candidates[:max(0, len(static_targets) - len(direct_free))]
    )
    if len(alias_indices) != len(static_targets):
        raise ValueError("Not enough safe low F14 alias slots")

    unused_existing = set(codetable) - used_indices
    # Index 0 is the fullwidth space: the original game leaves that glyph empty
    # and font_builder forces it transparent, so a character relocated onto it
    # simply vanishes.  No text ever references it, so it looks "unused" and --
    # since the pool is sorted -- it would be handed to the *first* relocation
    # every time.  That is how 令 disappeared from 「風紀委員の命令」: it sits on
    # reserved cell 0x004, the lowest used reserved index, so it was always
    # first in move_indices.
    #
    # low_range above already starts at 1 for the same reason, and both
    # rearrange_codetable and f14_context_aliases exclude 0 explicitly.
    destination_pool = sorted(
        (
            unused_existing
            | set(range(max(codetable) + 1, EXPANDED_GLYPH_COUNT))
        )
        - reserved
        - set(alias_indices)
        - {0}
    )
    move_indices = sorted(
        (used_indices & reserved)
        | (set(alias_indices) & used_indices)
    )
    if len(move_indices) > len(destination_pool):
        raise ValueError(
            f"Need {len(move_indices)} relocation destinations, but only "
            f"{len(destination_pool)} are free"
        )

    global_overrides = {}
    font_overrides = {}
    aliases = []
    for source_index, destination_index in zip(move_indices, destination_pool):
        character = codetable[source_index]
        global_overrides[character] = destination_index.to_bytes(2, "little")
        font_overrides[destination_index] = character
        aliases.append({
            "kind": "normal_move",
            "character": character,
            "source": source_index,
            "destination": destination_index,
        })

    static_overrides = {}
    for target_index, alias_index in zip(static_targets, alias_indices):
        character = codetable[target_index]
        static_overrides[character] = alias_index.to_bytes(2, "little")
        font_overrides[alias_index] = character
        aliases.append({
            "kind": "static_alias",
            "character": character,
            "source": target_index,
            "destination": alias_index,
        })

    # Player-entered Latin letters stay in RAM as the original codes
    # 0x034..0x04D.  Apply this policy only after the normal relocation plan is
    # complete: the Chinese characters currently occupying C-Y still need the
    # relocation above before those original cells can be painted back to A-Z.
    mixed_name_overrides = build_mixed_name_global_overrides(character_codes)
    shared_global_conflicts = sorted(
        set(global_overrides) & SHARED_GLYPH_CHARACTERS
    )
    if shared_global_conflicts:
        raise ValueError(
            "Normal relocation unexpectedly overrides mixed-name shared "
            f"characters: {shared_global_conflicts}"
        )
    shared_static_conflicts = sorted(
        set(static_overrides) & SHARED_GLYPH_CHARACTERS
    )
    if shared_static_conflicts:
        raise ValueError(
            "Static aliases would override mixed-name shared characters: "
            f"{shared_static_conflicts}"
        )

    released_indices = set(
        released_f14_context_alias_indices(character_codes)
    )
    font_conflicts = sorted(released_indices & set(font_overrides))
    if font_conflicts:
        raise ValueError(
            "Normal font overrides occupy mixed-name F14 alias cells: "
            f"{[hex(index) for index in font_conflicts]}"
        )
    override_target_conflicts = sorted(
        released_indices
        & {
            int.from_bytes(code, "little")
            for code in (
                list(global_overrides.values())
                + list(static_overrides.values())
            )
        }
    )
    if override_target_conflicts:
        raise ValueError(
            "Normal text aliases still encode into mixed-name F14 cells: "
            f"{[hex(index) for index in override_target_conflicts]}"
        )

    # Every translated text path receives this one global map.  The old glyphs
    # at the released indices remain in F13, while only F14 repaints those cells
    # with context-local Chinese aliases.
    global_overrides.update(mixed_name_overrides)
    effective_character_codes = dict(character_codes)
    effective_character_codes.update(global_overrides)
    still_using_released = sorted(
        (character, int.from_bytes(code, "little"))
        for character, code in effective_character_codes.items()
        if int.from_bytes(code, "little") in released_indices
    )
    if still_using_released:
        raise ValueError(
            "Mixed-name F14 alias cells are still globally encoded: "
            f"{still_using_released}"
        )
    for character, expected_index in ORIGINAL_FULLWIDTH_LATIN_INDICES.items():
        actual_index = int.from_bytes(
            global_overrides[character], "little"
        )
        if actual_index != expected_index:
            raise AssertionError(
                f"Fullwidth Latin {character} maps to {actual_index:#x}, "
                f"expected {expected_index:#x}"
            )

    highest_index = max(set(codetable) | set(font_overrides))
    if highest_index >= EXPANDED_GLYPH_COUNT:
        raise ValueError("Normal-text plan exceeds expanded F13")

    return UnifiedNormalTextPlan(
        global_character_overrides=global_overrides,
        section_character_overrides={
            section: dict(static_overrides)
            for section in STATIC_TEXT_SECTIONS
        },
        font_overrides=font_overrides,
        used_indices=frozenset(used_indices),
        static_indices=frozenset(static_indices),
        aliases=tuple(aliases),
        highest_index=highest_index,
    )
