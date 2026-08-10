"""Build-time code sharing used to keep mixed player names readable in F14.

Player-entered Latin letters are stored with the original game's codes
0x034..0x04D.  Those cells therefore have to contain A-Z in both fonts even
though the translated codetable normally places most letters elsewhere.

Re-encoding the translated text back onto the original Latin cells releases
19 low F14 cells.  Three more cells come from pairs whose rendered 12px glyphs
are byte-identical.  The 22 released cells are the destination pool for the 22
Chinese F14 context aliases that previously covered C-Z.
"""


F14_CAPACITY = 0x0567
BYTES_PER_1BPP_GLYPH = 24

FULLWIDTH_LATIN_CHARACTERS = tuple(
    chr(codepoint) for codepoint in range(0xFF21, 0xFF3B)
)
ORIGINAL_FULLWIDTH_LATIN_INDICES = {
    character: 0x034 + offset
    for offset, character in enumerate(FULLWIDTH_LATIN_CHARACTERS)
}

# The source and canonical characters render to exactly the same 12px bitmap.
# Keep the target indices explicit: 0x004 is also the original name-entry
# middle dot, while 0x295/0x296 are stable low F14 cells.
VISUAL_GLYPH_ALIASES = {
    "·": ("・", 0x004),
    "i": ("ｉ", 0x295),
    "f": ("ｆ", 0x296),
}

SHARED_GLYPH_CHARACTERS = frozenset(
    set(FULLWIDTH_LATIN_CHARACTERS) | set(VISUAL_GLYPH_ALIASES)
)

# This exact order is part of the compressed-layout budget.  A codetable
# rearrange must stop the build and trigger a fresh collision/RLE audit instead
# of silently selecting a different set of low cells.
EXPECTED_RELEASED_F14_CONTEXT_ALIAS_INDICES = (
    0x118, 0x1EA, 0x1EB, 0x1F2, 0x1F3, 0x1F4, 0x294, 0x297,
    0x306, 0x314, 0x315, 0x316, 0x318, 0x31D, 0x323, 0x329,
    0x339, 0x3D3, 0x405, 0x3C7, 0x547, 0x548,
)


def _index_of(character_codes, character):
    code = character_codes.get(character)
    if code is None:
        raise ValueError(f"Mixed-name character is absent from codetable: {character!r}")
    if isinstance(code, str):
        code = bytes.fromhex(code)
    if not isinstance(code, (bytes, bytearray)) or len(code) != 2:
        raise ValueError(
            f"Mixed-name character has an invalid code: {character!r}={code!r}"
        )
    return int.from_bytes(code, "little")


def build_mixed_name_global_overrides(character_codes):
    """Return the global text encodings that restore F14's original A-Z."""
    overrides = {
        character: index.to_bytes(2, "little")
        for character, index in ORIGINAL_FULLWIDTH_LATIN_INDICES.items()
    }

    for source, (canonical, expected_index) in VISUAL_GLYPH_ALIASES.items():
        actual_index = _index_of(character_codes, canonical)
        if actual_index != expected_index:
            raise ValueError(
                f"Visual alias target {canonical!r} moved from "
                f"{expected_index:#x} to {actual_index:#x}"
            )
        source_index = _index_of(character_codes, source)
        if source_index == expected_index:
            raise ValueError(
                f"Visual alias {source!r} no longer releases a distinct cell"
            )
        overrides[source] = expected_index.to_bytes(2, "little")

    if set(overrides) != SHARED_GLYPH_CHARACTERS:
        raise AssertionError("Mixed-name global override set is incomplete")
    return overrides


def released_f14_context_alias_indices(character_codes):
    """Return the ordered 22-cell pool released by the global overrides."""
    released_latin = sorted(
        source_index
        for character, target_index in ORIGINAL_FULLWIDTH_LATIN_INDICES.items()
        for source_index in (_index_of(character_codes, character),)
        if source_index != target_index and source_index < F14_CAPACITY
    )
    released_visual = [
        _index_of(character_codes, source)
        for source in VISUAL_GLYPH_ALIASES
    ]
    released = tuple(released_latin + released_visual)

    if released != EXPECTED_RELEASED_F14_CONTEXT_ALIAS_INDICES:
        raise ValueError(
            "Mixed-name released F14 cells changed; re-audit layout/RLE: "
            f"{[hex(index) for index in released]}"
        )
    if len(released) != 22:
        raise ValueError(
            f"Mixed-name layout must release exactly 22 F14 cells, got "
            f"{len(released)}"
        )
    if len(set(released)) != len(released):
        raise ValueError("Mixed-name layout releases duplicate F14 cells")
    if any(not 0 < index < F14_CAPACITY for index in released):
        raise ValueError(
            "Mixed-name released cells must be nonzero and inside F14"
        )

    target_indices = set(ORIGINAL_FULLWIDTH_LATIN_INDICES.values()) | {
        index for _, index in VISUAL_GLYPH_ALIASES.values()
    }
    overlap = sorted(set(released) & target_indices)
    if overlap:
        raise ValueError(
            "Mixed-name released cells overlap canonical targets: "
            f"{[hex(index) for index in overlap]}"
        )
    return released


def visual_glyph_code_pairs(character_codes):
    """Return ``(source, target)`` code pairs for byte-level font checks."""
    return tuple(
        (_index_of(character_codes, source), target_index)
        for source, (_, target_index) in VISUAL_GLYPH_ALIASES.items()
    )


def glyph_character_matches(character, painted_character):
    """Treat the three byte-identical visual aliases as the same glyph."""
    canonical = VISUAL_GLYPH_ALIASES.get(character, (character, None))[0]
    return painted_character == canonical


def validate_visual_alias_font_data(font_data, character_codes):
    """Fail if a font update makes any visual alias pair diverge."""
    font_data = bytes(font_data)
    mismatches = []
    for source_index, target_index in visual_glyph_code_pairs(character_codes):
        source_start = source_index * BYTES_PER_1BPP_GLYPH
        target_start = target_index * BYTES_PER_1BPP_GLYPH
        source = font_data[
            source_start:source_start + BYTES_PER_1BPP_GLYPH
        ]
        target = font_data[
            target_start:target_start + BYTES_PER_1BPP_GLYPH
        ]
        if (
            len(source) != BYTES_PER_1BPP_GLYPH
            or len(target) != BYTES_PER_1BPP_GLYPH
            or source != target
        ):
            mismatches.append((source_index, target_index))
    if mismatches:
        raise AssertionError(
            "Mixed-name visual glyph aliases are no longer byte-identical: "
            + " ".join(
                f"{source:#x}!={target:#x}"
                for source, target in mismatches
            )
        )


def _glyph_bytes(font_data, index):
    start = index * BYTES_PER_1BPP_GLYPH
    glyph = bytes(font_data[start:start + BYTES_PER_1BPP_GLYPH])
    if len(glyph) != BYTES_PER_1BPP_GLYPH:
        raise AssertionError(f"Font has no complete glyph at {index:#x}")
    return glyph


def validate_mixed_name_font_layout(
    dynamic_font_data,
    static_font_data,
    character_codes,
    context_aliases,
):
    """Validate the final F13/F14 physical glyph layout byte for byte."""
    validate_visual_alias_font_data(dynamic_font_data, character_codes)

    latin_mismatches = []
    for character, target_index in ORIGINAL_FULLWIDTH_LATIN_INDICES.items():
        source_index = _index_of(character_codes, character)
        expected = _glyph_bytes(dynamic_font_data, source_index)
        if (
            _glyph_bytes(dynamic_font_data, target_index) != expected
            or _glyph_bytes(static_font_data, target_index) != expected
        ):
            latin_mismatches.append((character, source_index, target_index))
    if latin_mismatches:
        raise AssertionError(
            "Mixed-name A-Z glyphs are not restored in both fonts: "
            + " ".join(
                f"{character}:{source:#x}->{target:#x}"
                for character, source, target in latin_mismatches
            )
        )

    canonical_mismatches = []
    for _, target_index in visual_glyph_code_pairs(character_codes):
        if _glyph_bytes(static_font_data, target_index) != _glyph_bytes(
            dynamic_font_data, target_index
        ):
            canonical_mismatches.append(target_index)
    if canonical_mismatches:
        raise AssertionError(
            "F14 changed canonical visual-alias glyphs: "
            f"{[hex(index) for index in canonical_mismatches]}"
        )

    alias_mismatches = []
    for alias in context_aliases:
        normal_index = alias["normal_code"]
        f14_index = alias["f14_code"]
        if _glyph_bytes(static_font_data, f14_index) != _glyph_bytes(
            dynamic_font_data, normal_index
        ):
            alias_mismatches.append(
                (alias["character"], normal_index, f14_index)
            )
    if alias_mismatches:
        raise AssertionError(
            "F14 context alias glyphs do not match F13: "
            + " ".join(
                f"{character}:{normal:#x}->{target:#x}"
                for character, normal, target in alias_mismatches
            )
        )
