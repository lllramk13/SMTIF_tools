"""Build low-code F14 aliases for selected static text contexts.

The original C-Z cells must now remain Latin so mixed Chinese/Latin player
names can use F14.  The aliases instead occupy 19 redundant translated-letter
cells plus three cells released by byte-identical visual glyph aliases.

Only the confirmed F14-rendered option and skill-name blocks receive these
alternate encodings.  Normal dialogue keeps its ordinary F13 codes.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from src.glyph_layout import DYNAMIC_SPECIAL_LOW_INDICES, glyph_indices
from src.font_builder import load_codetable
from src.mixed_name_layout import (
    SHARED_GLYPH_CHARACTERS,
    glyph_character_matches,
    released_f14_context_alias_indices,
)
from src.original_ui_glyphs import load_original_ui_glyph_overrides
from src.text_codec import load_character_codes
from src.text_records import choose_text, load_text_data


HERE = Path(__file__).resolve().parent
NEW_DIRECTORY = HERE.parent
DEFAULT_CODETABLE_PATH = NEW_DIRECTORY / "data" / "codetable.json"
DEFAULT_TEXT_PATH = NEW_DIRECTORY / "data" / "text.json"

F14_CAPACITY = 0x0567
ORIGINAL_NAME_GLYPH_INDICES = frozenset(
    set(DYNAMIC_SPECIAL_LOW_INDICES) | {0}
)

# Reserved cells the executable addresses by hardcoded glyph index, where an
# alias would be silently repainted over a glyph the original UI still draws by
# number.  Only two groups are evidenced in game:
#
#   (0x02A-0x033, the map header's fullwidth ０-９, used to live here.  Those
#    cells now carry our own digits as codetable pins instead, so they are not
#    part of the reserved pool at all -- see glyph_layout and DIGIT_PINS.)
#   0x034-0x035  fullwidth Ａ Ｂ  -- the save screen draws these by index.  The
#                allocator takes the *highest* free cells, and 0x035 was the
#                lowest one it reached, so 率's alias landed on Ｂ and the save
#                screen showed 率.  Ａ has to come along: protecting Ｂ alone
#                just moves the bottom of the range down onto it.
#   0x039        fullwidth Ｆ     -- the same header's floor suffix; aliasing
#                it is what produced 学校1＋.
#
# A-Z are now globally re-encoded to 0x034..0x04D and restored in F14, so
# ＮＯ DATA, UI labels and player names may all reference these cells safely.
# They remain unavailable as alias destinations; the 22 context aliases use
# the separate released pool calculated by mixed_name_layout.py.
HARDCODED_GLYPH_INDICES = frozenset()

# These blocks were confirmed in-game to draw through 0x800475FC.
F14_CONTEXT_RECORD_PREFIXES = (
    "F0094-00000000",
    # Item/common-magic descriptions shown in the green help panel.
    "F0094-00002070",
    # Character/demon skill descriptions shown in the same F14 panel.
    "F0094-00002D98",
    "F0076-00002C7C",
    "F0084-00000800",
    "F0084-0000E000",
    "F0094-00002630",
)
F14_CONTEXT_NAME_PREFIX = "F0094-00000000"
F14_EMBEDDED_UI_CHARACTERS = frozenset(("余",))
REQUIRED_CONTEXT_TRANSLATIONS = ("玲子", "雷霆")
PARTY_PRESET_NAMES = ("由美", "查理", "明")
KATAKANA_NAME = re.compile(r"^[ァ-ヶー・]+$")
EXPECTED_CONTEXT_ALIAS_CHARACTERS = tuple(
    "势苍蝇队伍区烧施／版蝙蝠周咆哮夹＋焚贯捆濒银"
)


@dataclass(frozen=True)
class F14ContextAliasPlan:
    record_character_overrides: dict[str, dict[str, bytes]]
    character_overrides: dict[str, bytes]
    font_overrides: dict[int, str]
    aliases: tuple[dict, ...]
    context_characters: frozenset[str]


def validate_encoded_record_alias_isolation(encoded_records, alias_plan):
    """Ensure the 22 repainted F14 cells never leak into F13 records."""
    alias_indices = set(alias_plan.font_overrides)
    allowed_prefixes = tuple(alias_plan.record_character_overrides)
    leaks = []
    high_context_codes = []

    for record in encoded_records:
        record_id = record["id"]
        is_f14_context = record_id.startswith(allowed_prefixes)
        encoded = record["encoded_text"]
        used = set()
        high = set()
        for position in range(0, len(encoded), 2):
            code = encoded[position:position + 2]
            if len(code) != 2 or code == b"\xFF\xFF":
                break
            if code[1] == 0xFF:
                continue
            index = int.from_bytes(code, "little")
            if index >= F14_CAPACITY:
                high.add(index)
            if index in alias_indices:
                used.add(index)
        if is_f14_context and high:
            high_context_codes.append((record_id, tuple(sorted(high))))
        if not is_f14_context and used:
            leaks.append((record_id, tuple(sorted(used))))

    if high_context_codes:
        raise AssertionError(
            "F14 records retained out-of-range glyph codes: "
            + " ".join(
                f"{record_id}={','.join(hex(index) for index in indices)}"
                for record_id, indices in high_context_codes[:8]
            )
        )
    if leaks:
        raise AssertionError(
            "F14-only alias codes leaked into normal records: "
            + " ".join(
                f"{record_id}={','.join(hex(index) for index in indices)}"
                for record_id, indices in leaks[:8]
            )
        )


def _selected_characters(
    text_data,
    character_codes,
    codetable,
    extra_context_texts=(),
):
    characters = set()
    matched_records = 0

    for records in text_data.values():
        for record in records:
            record_id = record.get("id", "")
            if not record_id.startswith(F14_CONTEXT_RECORD_PREFIXES):
                continue
            matched_records += 1
            for index in glyph_indices(
                character_codes,
                choose_text(record),
            ):
                character = codetable.get(index)
                if character is not None:
                    characters.add(character)

    if not matched_records:
        raise ValueError("No F14 context-alias records were found")

    for text in extra_context_texts:
        if not isinstance(text, str) or not text:
            raise ValueError("extra F14 context text must be non-empty")
        for index in glyph_indices(character_codes, text):
            character = codetable.get(index)
            if character is not None:
                characters.add(character)

    return characters


def _translated_party_names(text_data):
    names = list(PARTY_PRESET_NAMES)
    for record in text_data.get("texts", ()):
        source = record.get("source")
        translation = record.get("translation")
        if (
            record.get("id", "").startswith("F0040")
            and isinstance(source, str)
            and KATAKANA_NAME.match(source.strip() or "x")
            and isinstance(translation, str)
            and translation
        ):
            names.append(translation)
    return names


def _translated_context_names(text_data):
    return tuple(
        record["translation"]
        for records in text_data.values()
        for record in records
        if (
            record.get("id", "").startswith(F14_CONTEXT_NAME_PREFIX)
            and isinstance(record.get("translation"), str)
            and record["translation"]
        )
    )


def build_f14_context_alias_plan(
    *,
    text_path=DEFAULT_TEXT_PATH,
    codetable_path=DEFAULT_CODETABLE_PATH,
    global_character_overrides=None,
    existing_font_overrides=None,
    extra_context_texts=(),
):
    """Build low-code aliases for the confirmed F14-only record blocks."""
    text_path = Path(text_path)
    codetable_path = Path(codetable_path)
    codetable = load_codetable(codetable_path)
    base_character_codes = load_character_codes(codetable_path)
    text_data = load_text_data(text_path)

    context_characters = (
        _selected_characters(
            text_data,
            base_character_codes,
            codetable,
            extra_context_texts,
        )
        | F14_EMBEDDED_UI_CHARACTERS
    )

    effective_character_codes = dict(base_character_codes)
    effective_character_codes.update(global_character_overrides or {})

    final_f14_glyphs = dict(codetable)
    final_f14_glyphs.update(existing_font_overrides or {})
    # This is the state before the context aliases are applied in build.py.
    final_f14_glyphs.update(load_original_ui_glyph_overrides())

    alias_characters = []
    for character in context_characters:
        code = effective_character_codes.get(character)
        if code is None:
            raise ValueError(
                f"F14 context character is missing from codetable: {character}"
            )
        index = int.from_bytes(code, "little")
        if (
            index >= F14_CAPACITY
            or not glyph_character_matches(
                character, final_f14_glyphs.get(index)
            )
        ):
            alias_characters.append(character)

    alias_characters.sort(
        key=lambda character: int.from_bytes(
            base_character_codes[character],
            "little",
        )
    )

    if tuple(alias_characters) != EXPECTED_CONTEXT_ALIAS_CHARACTERS:
        raise ValueError(
            "F14 context alias set changed; re-audit the fixed 22-cell layout: "
            f"{''.join(alias_characters)}"
        )

    # These are the 19 low cells vacated by globally re-pinning fullwidth A-Z,
    # followed by the three byte-identical visual-alias source cells.  The
    # order is deliberate: it produces a 23,486-byte minimum RLE main block,
    # safely inside F0014's fixed 23,541-byte budget.
    available_indices = released_f14_context_alias_indices(
        base_character_codes
    )
    encoded_users = sorted(
        (character, int.from_bytes(code, "little"))
        for character, code in effective_character_codes.items()
        if int.from_bytes(code, "little") in set(available_indices)
    )
    if encoded_users:
        raise ValueError(
            "Released F14 alias cells are still globally encoded: "
            f"{encoded_users}"
        )
    font_conflicts = sorted(
        set(available_indices) & set(existing_font_overrides or {})
    )
    if font_conflicts:
        raise ValueError(
            "Existing font overrides occupy released F14 alias cells: "
            f"{[hex(index) for index in font_conflicts]}"
        )
    if len(alias_characters) > len(available_indices):
        raise ValueError(
            f"F14 contexts need {len(alias_characters)} aliases, but only "
            f"{len(available_indices)} released cells are available"
        )
    selected_indices = available_indices[:len(alias_characters)]

    character_overrides = {}
    font_overrides = {}
    aliases = []
    for character, index in zip(alias_characters, selected_indices):
        character_overrides[character] = index.to_bytes(2, "little")
        font_overrides[index] = character
        aliases.append({
            "character": character,
            "normal_code": int.from_bytes(
                effective_character_codes[character],
                "little",
            ),
            "f14_code": index,
        })

    final_f14_glyphs.update(font_overrides)
    shared_alias_conflicts = sorted(
        set(character_overrides) & SHARED_GLYPH_CHARACTERS
    )
    if shared_alias_conflicts:
        raise AssertionError(
            "F14 context aliases override mixed-name shared characters: "
            f"{shared_alias_conflicts}"
        )
    context_codes = dict(effective_character_codes)
    context_codes.update(character_overrides)
    for character in context_characters:
        index = int.from_bytes(context_codes[character], "little")
        if index >= F14_CAPACITY:
            raise AssertionError(
                f"F14 context character {character} still uses high "
                f"code {index:#x}"
            )
        if not glyph_character_matches(
            character, final_f14_glyphs.get(index)
        ):
            raise AssertionError(
                f"F14 context character {character} maps to {index:#x}, "
                "but that cell contains another glyph"
            )

    selected_translations = tuple(
        choose_text(record)
        for records in text_data.values()
        for record in records
        if record.get("id", "").startswith(F14_CONTEXT_RECORD_PREFIXES)
    )
    for translation in REQUIRED_CONTEXT_TRANSLATIONS:
        if translation not in selected_translations:
            raise ValueError(
                f"Required F14 regression text is missing: {translation!r}"
            )
        for character in translation:
            index = int.from_bytes(context_codes[character], "little")
            if (
                index >= F14_CAPACITY
                or not glyph_character_matches(
                    character, final_f14_glyphs.get(index)
                )
            ):
                raise AssertionError(
                    f"Required F14 regression text {translation!r} is not "
                    f"safe: {character!r} maps to {index:#x}"
                )

    # The runtime wrapper chooses the original small font only when every
    # glyph in a name belongs to the exact original name-entry code set.
    # Every translated name must therefore contain a non-reserved code, and
    # every one of its codes must still fit F14.
    for name in _translated_party_names(text_data):
        indices = glyph_indices(effective_character_codes, name)
        if indices and indices <= ORIGINAL_NAME_GLYPH_INDICES:
            raise ValueError(
                f"Translated party name would be misclassified as an "
                f"original keyboard name: {name!r}"
            )
        high = sorted(index for index in indices if index >= F14_CAPACITY)
        if high:
            raise ValueError(
                f"Translated party name {name!r} has F14-out-of-range "
                f"codes: {[hex(index) for index in high]}"
            )

    # The F0094 preset-name table is encoded with the context aliases above,
    # so validate it against the context-specific code map.  In particular,
    # this keeps 玲子 safe without consuming another globally reserved F14
    # cell or changing how save/RAM names are encoded elsewhere.
    for name in _translated_context_names(text_data):
        indices = glyph_indices(context_codes, name)
        if indices and indices <= ORIGINAL_NAME_GLYPH_INDICES:
            raise ValueError(
                f"Translated context name would be misclassified as an "
                f"original keyboard name: {name!r}"
            )
        high = sorted(index for index in indices if index >= F14_CAPACITY)
        if high:
            raise ValueError(
                f"Translated context name {name!r} has F14-out-of-range "
                f"codes: {[hex(index) for index in high]}"
            )

    record_character_overrides = {
        prefix: dict(character_overrides)
        for prefix in F14_CONTEXT_RECORD_PREFIXES
    }
    return F14ContextAliasPlan(
        record_character_overrides=record_character_overrides,
        character_overrides=character_overrides,
        font_overrides=font_overrides,
        aliases=tuple(aliases),
        context_characters=frozenset(context_characters),
    )
