"""Patch name rendering inside the code overlays.

Party/demon names are stored as 16-bit internal glyph indices.  The original
renderer ``0x80046FEC`` first converts those indices back to Shift-JIS
(``0x8004AE8C``) and then draws them through the small system font whose atlas
lives in ``F0012.BIN``.  That conversion only knows the original
punctuation/kana range, so every translated Chinese index collapses to the
shared fallback tile and the name shows up as "....".

The hybrid wrapper at ``0x8004AD6C`` preserves original keyboard-entered names
on the small-font path and sends translated names to ``0x800475FC``.  The two
SLPM call sites are patched by ``CN.asm``; the remaining sites live in code
overlays and are handled here.

Swapping a ``jal`` target is a 4-byte, equal-length edit, so the overlays keep
their exact size and the in-place overlay injection stays valid.
"""
from pathlib import Path

SMALL_FONT_NAME_RENDERER = 0x80046FEC
STATIC_FONT_RENDERER = 0x800475FC
HYBRID_NAME_RENDERER = 0x8004AD6C

# Expected call sites, discovered by scanning the clean overlays for
# ``jal 0x80046FEC``.  Kept explicit so an unexpected layout change fails the
# build instead of silently patching something else.
EXPECTED_NAME_RENDERER_SITES = {
    "F0048": (0x6210, 0x686C, 0x79BC),
    "F0049": (0x43F0,),
    "F0061": (0x670, 0x6DC),
    "F0091": (0x374, 0xA7C),
}

# The opposite mistake: SAVE/LOAD draws its slot strings straight through F14.
# F14's low cells now hold the context aliases, so an original keyboard-entered
# name -- and the built-in ＮＯＤＡＴＡ placeholder, stored as
# ``Ｎ Ｏ {FFFE} Ｄ Ａ Ｔ Ａ`` -- comes out as unrelated Chinese glyphs
# (Ｎ→獠, Ｏ→冥, Ｔ→奢).  Route these through the same hybrid wrapper so
# original codes go back to the small font while translated names stay on F14.
#
# All three sites live in the slot-drawing routine at F0088 0x2CB4:
#   0x2D3C  s0+0x20, a3|=0xF4  fixed label string
#   0x2D84  s0+0x1C, a3|=0xE1  slot name / ＮＯＤＡＴＡ
#   0x2E0C  s0+0x1C, a3|=0xE1  same field, no-extra-label branch
# The wrapper's F14 leg ORs in a3 bit 0 (single-pass); 0xE1 already has it, so
# the two name draws keep byte-identical F14 behaviour.  Only the fixed label
# at 0x2D3C loses F14's second shadow pass.
#
# Both renderers take the drawing buffer from the caller's sp+0x10
# (0x80046FEC: -112 frame, reads 128(sp); 0x800475FC: -56 frame, reads 72(sp)),
# so swapping either way at a call site needs no stack fixup.
# Disabled 2026-07-28.  Redirecting these three had no observable effect on
# the ＮＯＤＡＴＡ garbling it was meant to fix (that turned out to be a
# missing slpm_text record at 0x0E6E20), but it does change how the save
# slot strings are rendered -- 0x2D3C's a3 lacks bit 0, so the wrapper
# forced F14 single-pass on it.  A tester's card then showed the FILE
# label and ＮＯ　ＤＡＴＡ collapsing onto one line; the previously shipped
# build and a different card are both fine.  Left here documented rather
# than deleted: if a save-slot name ever needs the hybrid route, this is
# the table, but it must be validated on the failing card first.
EXPECTED_STATIC_NAME_RENDERER_SITES = {}


def _jal(address):
    if address & 3:
        raise ValueError(f"jal target must be word aligned: {address:#x}")
    return (0x0C000000 | ((address >> 2) & 0x03FFFFFF)).to_bytes(4, "little")


def _find_calls(data, target):
    instruction = _jal(target)
    return tuple(
        offset
        for offset in range(0, len(data) - 3, 4)
        if data[offset:offset + 4] == instruction
    )


def apply_overlay_name_renderer_patches(replacements, source_directory):
    """Point overlay name rendering at the hybrid name renderer.

    ``replacements`` is the build's disc-replacement map and is updated in
    place, reusing any earlier overlay text injection as the base so the two
    passes compose.
    """
    source_directory = Path(source_directory)
    patched_files = 0
    patched_sites = 0

    tables = (
        (SMALL_FONT_NAME_RENDERER, EXPECTED_NAME_RENDERER_SITES),
        (STATIC_FONT_RENDERER, EXPECTED_STATIC_NAME_RENDERER_SITES),
    )
    for original_renderer, sites in tables:
        for file_name, expected_offsets in sites.items():
            key = f"D/{file_name}.BIN"
            base = replacements.get(key)
            if base is None:
                base = (source_directory / f"{file_name}.BIN").read_bytes()
            if not isinstance(base, (bytes, bytearray)):
                raise TypeError(f"{key}: overlay data must be bytes")

            data = bytearray(base)
            found = _find_calls(data, original_renderer)
            if found != tuple(expected_offsets):
                raise AssertionError(
                    f"{key}: expected jal {original_renderer:#x} at "
                    f"{[hex(o) for o in expected_offsets]}, found "
                    f"{[hex(o) for o in found]}"
                )

            for offset in found:
                data[offset:offset + 4] = _jal(HYBRID_NAME_RENDERER)
                patched_sites += 1

            patched = bytes(data)
            if len(patched) != len(base):
                raise AssertionError(f"{key}: overlay size changed")
            if _find_calls(patched, original_renderer):
                raise AssertionError(
                    f"{key}: jal {original_renderer:#x} survived"
                )
            if len(_find_calls(patched, HYBRID_NAME_RENDERER)) < len(found):
                raise AssertionError(
                    f"{key}: hybrid name call verification failed"
                )

            replacements[key] = patched
            patched_files += 1

    return patched_files, patched_sites
