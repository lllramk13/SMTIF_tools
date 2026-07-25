"""Safely bridge selected direct Shift-JIS UI strings to the F14 renderer.

The executable contains byte strings that are normally drawn by 0x80046D08.
That renderer supports the original UI's limited Japanese repertoire; merely
encoding Chinese as Shift-JIS makes it draw each unsupported byte as a kana
glyph.  For the two upgrade-screen strings we instead:

* store the translation as the game's 16-bit internal codes in the same slot;
* replace that string's ``jal 0x80046D08`` with ``jal 0x800475FC``.

Both renderers accept the same register arguments, so coordinates and colour
stay untouched.  Their drawing-buffer stack argument differs: the direct
renderer reads ``sp+0x14`` while F14 reads ``sp+0x10``.  Each call's delay-slot
store is therefore patched along with the ``jal``.
Other direct strings remain original until their individual call sites are
identified and converted.
"""
from dataclasses import dataclass
from pathlib import Path

from src.text_codec import encode_text, load_character_codes


HERE = Path(__file__).resolve().parent
PROJECT_DIRECTORY = HERE.parent.parent
DEFAULT_BASE_SLPM_PATH = PROJECT_DIRECTORY / "extrac" / "SLPM_871.54"
DEFAULT_CODETABLE_PATH = HERE.parent / "data" / "codetable.json"

F14_CAPACITY = 0x0567
DIRECT_UI_RENDERER = 0x80046D08
F14_UI_RENDERER = 0x800475FC
DIRECT_BUFFER_STORE = bytes.fromhex("1400A2AF")  # sw v0,0x14(sp)
F14_BUFFER_STORE = bytes.fromhex("1000A2AF")  # sw v0,0x10(sp)


@dataclass(frozen=True)
class F14UiRecord:
    record_id: str
    offset: int
    source: str
    translation: str
    renderer_call_offset: int


@dataclass(frozen=True)
class ShiftJisUiPlan:
    text_patches: tuple[dict, ...]
    instruction_patches: tuple[dict, ...]


F14_UI_RECORDS = (
    F14UiRecord(
        "upgrade_confirm",
        0x0E8E2C,
        "これでよろしいですか？",
        "这样可以吗？",
        0x06DD70,
    ),
    F14UiRecord(
        "remaining_points",
        0x0E8E44,
        "のこりポイント",
        "剩余点数",
        0x06E320,
    ),
)


def _jal(address):
    instruction = 0x0C000000 | ((address >> 2) & 0x03FFFFFF)
    return instruction.to_bytes(4, "little")


def build_shift_jis_ui_plan(
    *,
    base_slpm_path=DEFAULT_BASE_SLPM_PATH,
    codetable_path=DEFAULT_CODETABLE_PATH,
    character_overrides=None,
):
    """Build fixed-slot F14 text and renderer-call patches."""
    base_data = Path(base_slpm_path).read_bytes()
    character_codes = load_character_codes(codetable_path)
    character_codes.update(character_overrides or {})

    text_patches = []
    instruction_patches = []
    previous_text_end = -1
    seen_call_offsets = set()

    for record in sorted(F14_UI_RECORDS, key=lambda item: item.offset):
        source = record.source.encode("shift_jis")
        expected_slot = source + b"\x00"
        max_bytes = len(expected_slot)
        end = record.offset + max_bytes

        if record.offset < previous_text_end:
            raise ValueError(f"{record.record_id}: UI text slots overlap")
        previous_text_end = end
        actual_slot = base_data[record.offset:end]
        if actual_slot != expected_slot:
            raise AssertionError(
                f"{record.record_id}: unexpected original bytes at "
                f"{record.offset:#x}; expected {expected_slot.hex()}, "
                f"got {actual_slot.hex()}"
            )

        encoded = encode_text(character_codes, record.translation)
        if len(encoded) > max_bytes:
            raise ValueError(
                f"{record.record_id}: F14 text needs {len(encoded)} bytes, "
                f"slot has {max_bytes}"
            )
        for character in record.translation:
            code = character_codes.get(character)
            if code is None:
                raise ValueError(
                    f"{record.record_id}: missing code for {character!r}"
                )
            index = int.from_bytes(code, "little")
            if index >= F14_CAPACITY:
                raise ValueError(
                    f"{record.record_id}: {character!r} uses {index:#x}, "
                    f"outside F14 capacity {F14_CAPACITY:#x}"
                )

        text_patches.append({
            "id": f"f14_ui:{record.record_id}",
            "offset": record.offset,
            "max_bytes": max_bytes,
            "text": record.translation,
            "data": encoded + (b"\x00" * (max_bytes - len(encoded))),
            "encoded_length": len(encoded),
        })

        call_offset = record.renderer_call_offset
        if call_offset in seen_call_offsets:
            raise ValueError(
                f"{record.record_id}: duplicate renderer call offset"
            )
        seen_call_offsets.add(call_offset)
        expected_call = _jal(DIRECT_UI_RENDERER)
        actual_call = base_data[call_offset:call_offset + 4]
        if actual_call != expected_call:
            raise AssertionError(
                f"{record.record_id}: unexpected renderer call at "
                f"{call_offset:#x}; expected {expected_call.hex()}, "
                f"got {actual_call.hex()}"
            )
        instruction_patches.append({
            "id": f"f14_ui_renderer:{record.record_id}",
            "offset": call_offset,
            "expected": expected_call,
            "data": _jal(F14_UI_RENDERER),
        })
        buffer_store_offset = call_offset + 4
        actual_buffer_store = base_data[
            buffer_store_offset:buffer_store_offset + 4
        ]
        if actual_buffer_store != DIRECT_BUFFER_STORE:
            raise AssertionError(
                f"{record.record_id}: unexpected drawing-buffer store at "
                f"{buffer_store_offset:#x}; expected "
                f"{DIRECT_BUFFER_STORE.hex()}, got "
                f"{actual_buffer_store.hex()}"
            )
        instruction_patches.append({
            "id": f"f14_ui_buffer:{record.record_id}",
            "offset": buffer_store_offset,
            "expected": DIRECT_BUFFER_STORE,
            "data": F14_BUFFER_STORE,
        })

    return ShiftJisUiPlan(
        text_patches=tuple(text_patches),
        instruction_patches=tuple(instruction_patches),
    )
