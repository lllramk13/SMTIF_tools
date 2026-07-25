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

    for file_name, expected_offsets in EXPECTED_NAME_RENDERER_SITES.items():
        key = f"D/{file_name}.BIN"
        base = replacements.get(key)
        if base is None:
            base = (source_directory / f"{file_name}.BIN").read_bytes()
        if not isinstance(base, (bytes, bytearray)):
            raise TypeError(f"{key}: overlay data must be bytes")

        data = bytearray(base)
        found = _find_calls(data, SMALL_FONT_NAME_RENDERER)
        if found != tuple(expected_offsets):
            raise AssertionError(
                f"{key}: expected jal {SMALL_FONT_NAME_RENDERER:#x} at "
                f"{[hex(o) for o in expected_offsets]}, found "
                f"{[hex(o) for o in found]}"
            )

        for offset in found:
            data[offset:offset + 4] = _jal(HYBRID_NAME_RENDERER)
            patched_sites += 1

        patched = bytes(data)
        if len(patched) != len(base):
            raise AssertionError(f"{key}: overlay size changed")
        if _find_calls(patched, SMALL_FONT_NAME_RENDERER):
            raise AssertionError(f"{key}: small-font name call survived")
        if len(_find_calls(patched, HYBRID_NAME_RENDERER)) < len(found):
            raise AssertionError(
                f"{key}: hybrid name call verification failed"
            )

        replacements[key] = patched
        patched_files += 1

    return patched_files, patched_sites
