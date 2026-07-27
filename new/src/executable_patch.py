import hashlib
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
PREWORK_DIR = PROJECT_DIR / 'PreWork' / 'if备案'
BASE_SLPM_PATH = PROJECT_DIR / 'extrac' / 'SLPM_871.54'
SOURCE_ASM_PATH = HERE / 'CN.asm'
ARMIPS_PATH = PREWORK_DIR / 'armips.exe'
BUILD_DIR = HERE.parent / 'build'
ARMIPS_WORK_DIR = BUILD_DIR / 'armips'
OUTPUT_SLPM_PATH = BUILD_DIR / 'SLPM_871.54'

EXPECTED_BASE_SHA256 = (
    '8F06D6B81DE1BAC70D3658424AFC635C42F8AC3B2F727CAF6BF88D99B4B31CF4'
)
LOAD_ADDRESS = 0x8000F800
STATIC_WIDTH_TABLE_ADDRESS = 0x800F2910
STAT_ABBREVIATION_TABLE_OFFSET = 0xE5C20
STAT_ABBREVIATION_ENTRY_SIZE = 6
LUCK_STAT_ENTRY_INDEX = 5
ORIGINAL_LUCK_GLYPH_INDEX = 0x0131
SIMPLIFIED_LUCK_GLYPH_INDEX = 0x0180
# Intelligence stat: show 智 instead of the original 知.  The glyph code for
# 智 is resolved from the codetable at build time (rearranges move it), and it
# must stay < 0x567 because the status screen renders from F14.
INTELLIGENCE_STAT_ENTRY_INDEX = 1
ORIGINAL_INTELLIGENCE_GLYPH_INDEX = 0x03CD  # 知
INTELLIGENCE_STAT_CHARACTER = '智'

# Name-plural suffix: the party/battle name builder appends a hardcoded glyph
# code after a character's name (Japanese 達 "-tachi"/"and the others").  The
# instruction `addiu $a1, $zero, 0x03BB` at file 0x1D6B0 loads that code; the
# next `sh $a1, ($a0)` writes it into the name buffer.  0x03BB (達) now maps to
# an unrelated Chinese glyph after the codetable rearrange, so retarget the
# immediate to 等 ("<name>等"), resolved from the codetable at build time.
NAME_PLURAL_INSTRUCTION_OFFSET = 0x1D6B0
ORIGINAL_NAME_PLURAL_INSTRUCTION = bytes.fromhex('bb030524')  # addiu a1,zero,0x3BB
NAME_PLURAL_CHARACTER = '等'
# Both hardcoded UI glyphs render through F14.  Capacity is 0x6E4 since F14 was
# widened to 252x252 (441 glyphs/plane); see F14_CAPACITY_RE.md.
STATIC_FONT_CAPACITY = 0x567


def resolve_static_ui_glyph(character: str) -> int:
    """Look up a hardcoded UI character's glyph code from the codetable."""
    from src.text_codec import load_character_codes

    character_codes = load_character_codes(
        BUILD_DIR.parent / 'data' / 'codetable.json'
    )
    code_bytes = character_codes.get(character)
    if code_bytes is None:
        raise ValueError(f'hardcoded UI character missing from codetable: {character}')
    code = int.from_bytes(code_bytes, 'little')
    if code >= STATIC_FONT_CAPACITY:
        raise ValueError(
            f'hardcoded UI character {character} sits at {code:#x}, beyond '
            f'F14 capacity {STATIC_FONT_CAPACITY:#x}; add it to the static '
            'set in tools/rearrange_codetable.py and rerun the rearrange'
        )
    return code


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def virtual_address_to_file_offset(address: int) -> int:
    return address - LOAD_ADDRESS


def normalize_asm(source: str) -> str:
    """Remove the stray ARM-only .pool directive from the PSX/MIPS patch."""
    lines = source.splitlines()
    pool_lines = [line for line in lines if line.strip().lower() == '.pool']
    if len(pool_lines) > 1:
        raise ValueError(
            f'Expected at most one .pool directive in CN.asm, got '
            f'{len(pool_lines)}'
        )
    lines = [line for line in lines if line.strip().lower() != '.pool']
    return '\n'.join(lines) + '\n'


def patch_executable(
    base_slpm_path=BASE_SLPM_PATH,
    source_asm_path=SOURCE_ASM_PATH,
    armips_path=ARMIPS_PATH,
    output_path=OUTPUT_SLPM_PATH,
    width_table_overrides=None,
    embedded_text_patches=None,
    instruction_patches=None,
):
    base_slpm_path = Path(base_slpm_path)
    source_asm_path = Path(source_asm_path)
    armips_path = Path(armips_path)
    output_path = Path(output_path)

    base_data = base_slpm_path.read_bytes()
    base_hash = sha256(base_data)
    if base_hash != EXPECTED_BASE_SHA256:
        raise ValueError(
            f'Unexpected base SLPM SHA-256: {base_hash}; expected '
            f'{EXPECTED_BASE_SHA256}'
        )

    ARMIPS_WORK_DIR.mkdir(parents=True, exist_ok=True)
    work_base = ARMIPS_WORK_DIR / 'base_SLPM_871.54'
    work_asm = ARMIPS_WORK_DIR / 'CN.asm'
    work_output = ARMIPS_WORK_DIR / 'SLPM_871.54'

    shutil.copyfile(base_slpm_path, work_base)
    normalized_asm = normalize_asm(source_asm_path.read_text(encoding='utf-8'))
    work_asm.write_text(normalized_asm, encoding='utf-8', newline='\n')
    work_output.unlink(missing_ok=True)

    result = subprocess.run(
        [str(armips_path), work_asm.name],
        cwd=ARMIPS_WORK_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'armips failed with exit code {result.returncode}\n'
            f'{result.stdout}{result.stderr}'
        )
    if not work_output.is_file():
        raise FileNotFoundError('armips did not create SLPM_871.54')

    patched_data = work_output.read_bytes()
    if len(patched_data) != len(base_data):
        raise ValueError(
            f'Patched SLPM size changed from {len(base_data)} to '
            f'{len(patched_data)} bytes'
        )

    expected_opcodes = {
        0x8004ACB8: bytes.fromhex('FFFF8430'),
        0x8004AD4C: bytes.fromhex('1800C228'),
        0x8004AD58: bytes.fromhex('0800E003'),
        0x8004AD60: bytes.fromhex('00000000'),
        0x8004AD64: bytes.fromhex('00000000'),
        0x8004AD68: bytes.fromhex('00000000'),
        0x80049578: bytes.fromhex('CE0A0224'),
        0x8005B2E4: bytes.fromhex('0C000724'),
        0x8004A064: bytes.fromhex('0C000724'),
        0x8006C27C: bytes.fromhex('5B2B010C'),
        # Keep both known name sites on the hybrid route; the MARKER overflow
        # is fixed at its allocation-size estimator instead.
        0x8006D9E4: bytes.fromhex('5B2B010C'),
        0x80074F70: bytes.fromhex('5B2B010C'),  # SAVE/LOAD list -> hybrid
        0x8004AD6C: bytes.fromhex('21408000'),
        0x8004ADD4: bytes.fromhex('E6FF2011'),
        0x8004ADE8: bytes.fromhex('7F1D0108'),
        0x8004ADEC: bytes.fromhex('0100E734'),  # ori a3,a3,1: no F14 shadow
        0x8004ADF0: bytes.fromhex('FB1B0108'),
        0x8005C1D0: bytes.fromhex('C0100200'),
        # Renderer entries remain byte-for-byte original.
        0x80046864: bytes.fromhex('A8FFBD27'),
        0x80046868: bytes.fromhex('4000B4AF'),
        0x80046FEC: bytes.fromhex('90FFBD27'),
        0x80046FF0: bytes.fromhex('6000B2AF'),
        0x800475FC: bytes.fromhex('C8FFBD27'),
        0x80047600: bytes.fromhex('1180023C'),
        0x80046980: bytes.fromhex('00008392'),  # original initial lbu
        0x80046984: bytes.fromhex('6C00B18F'),
        0x80046B28: bytes.fromhex('00000000'),
        0x80046B2C: bytes.fromhex('9CFF6014'),
        0x80047C94: bytes.fromhex('8F514314'),  # bne -> 0x8005C2D4
        0x80047C98: bytes.fromhex('00000000'),  # original delay-slot nop
        0x8004AE70: bytes.fromhex('00000000'),  # original load-delay nop
        0x8004AE74: bytes.fromhex('E8FF4014'),  # original converter back-edge
        # MARKER's type-6 F14 object needs 0x100 bytes for six NODATA glyphs
        # with shadow, while its live descriptor contained 0xD0.  Match that
        # exact stride so other valid type-6 objects (notably EQUIP) are not
        # enlarged and corrupted.
        0x80084E94: bytes.fromhex('631D010C'),  # guessed test63 hook removed
        0x8006F0A8: bytes.fromhex('A6700108'),  # j 0x8005C298
        0x8006F0AC: bytes.fromhex('00141E00'),  # original type shift, delay
        0x8005C294: bytes.fromhex('00000000'),  # decoder jr delay slot
        0x8005C298: bytes.fromhex('03140200'),  # sra v0,v0,16
        0x8005C2A8: bytes.fromhex('0008288E'),  # lw t0,0x800(s1)
        0x8005C2AC: bytes.fromhex('30FF0925'),  # addiu t1,t0,-0xD0
        0x8005C2B0: bytes.fromhex('03002015'),  # bne t1,zero,done
        0x8005C2B8: bytes.fromhex('00010834'),  # ori t0,zero,0x100
        0x8005C2BC: bytes.fromhex('000828AE'),  # sw t0,0x800(s1)
        0x8005C2C0: bytes.fromhex('2CBC0108'),  # j 0x8006F0B0
        0x8005C2C8: bytes.fromhex('0100E734'),  # ori a3,a3,1
        0x8005C2CC: bytes.fromhex('7F1D0108'),  # j 0x800475FC
        0x8005C2D0: bytes.fromhex('00000000'),
        0x8005C2D4: bytes.fromhex('9AFF4124'),  # addiu at,v0,-0x66
        0x8005C2D8: bytes.fromhex('92AE2014'),  # bne -> original state path
        0x8005C2DC: bytes.fromhex('00000000'),
        0x8005C2E0: bytes.fromhex('5A1F0108'),  # j source-packet advance
        0x8005C2E4: bytes.fromhex('00000000'),
        0x800874D4: bytes.fromhex('191A010C'),  # original renderer call restored
        0x8005C2EC: bytes.fromhex('D8FFBD27'),  # next function is untouched
    }
    for address, expected in expected_opcodes.items():
        offset = virtual_address_to_file_offset(address)
        actual = patched_data[offset:offset + len(expected)]
        if actual != expected:
            raise AssertionError(
                f'Patch verification failed at {address:#010x}: '
                f'expected {expected.hex()}, got {actual.hex()}'
            )

    armips_changed_bytes = sum(
        old != new for old, new in zip(base_data, patched_data)
    )
    if armips_changed_bytes != 483:
        raise AssertionError(
            f'Expected CN.asm to change 483 bytes, got {armips_changed_bytes}'
        )

    patched_data = bytearray(patched_data)

    previous_instruction_end = -1
    for patch in sorted(
        instruction_patches or (),
        key=lambda item: item["offset"],
    ):
        patch_id = patch.get("id", "<unknown>")
        offset = patch.get("offset")
        expected = patch.get("expected")
        data = patch.get("data")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError(f"{patch_id}: invalid instruction offset")
        if (
            not isinstance(expected, bytes)
            or not isinstance(data, bytes)
            or not expected
            or len(data) != len(expected)
        ):
            raise ValueError(
                f"{patch_id}: instruction patch needs equal non-empty bytes"
            )
        end = offset + len(data)
        if end > len(patched_data):
            raise ValueError(f"{patch_id}: instruction patch exceeds SLPM")
        if offset < previous_instruction_end:
            raise ValueError(f"{patch_id}: instruction patches overlap")
        previous_instruction_end = end

        actual = bytes(patched_data[offset:end])
        if actual != expected:
            raise AssertionError(
                f"{patch_id}: expected {expected.hex()} at {offset:#x}, "
                f"got {actual.hex()}"
            )
        patched_data[offset:end] = data

    # The status screen stores six glyph indices directly in the executable.
    # Replace the original Japanese/traditional 運 entry with the simplified
    # Chinese 运 glyph already present in the generated F14 font.
    luck_stat_offset = (
        STAT_ABBREVIATION_TABLE_OFFSET
        + LUCK_STAT_ENTRY_INDEX * STAT_ABBREVIATION_ENTRY_SIZE
    )
    expected_luck_code = ORIGINAL_LUCK_GLYPH_INDEX.to_bytes(2, 'little')
    actual_luck_code = bytes(patched_data[luck_stat_offset:luck_stat_offset + 2])
    if actual_luck_code != expected_luck_code:
        raise AssertionError(
            'Unexpected original luck-stat glyph code at '
            f'{luck_stat_offset:#x}: expected {expected_luck_code.hex()}, '
            f'got {actual_luck_code.hex()}'
        )
    simplified_luck_code = SIMPLIFIED_LUCK_GLYPH_INDEX.to_bytes(2, 'little')
    patched_data[luck_stat_offset:luck_stat_offset + 2] = simplified_luck_code

    # Intelligence stat abbreviation: 知 -> 智.
    intelligence_stat_offset = (
        STAT_ABBREVIATION_TABLE_OFFSET
        + INTELLIGENCE_STAT_ENTRY_INDEX * STAT_ABBREVIATION_ENTRY_SIZE
    )
    expected_intelligence_code = ORIGINAL_INTELLIGENCE_GLYPH_INDEX.to_bytes(2, 'little')
    actual_intelligence_code = bytes(
        patched_data[intelligence_stat_offset:intelligence_stat_offset + 2]
    )
    if actual_intelligence_code != expected_intelligence_code:
        raise AssertionError(
            'Unexpected original intelligence-stat glyph code at '
            f'{intelligence_stat_offset:#x}: expected '
            f'{expected_intelligence_code.hex()}, '
            f'got {actual_intelligence_code.hex()}'
        )
    patched_data[intelligence_stat_offset:intelligence_stat_offset + 2] = (
        resolve_static_ui_glyph(INTELLIGENCE_STAT_CHARACTER).to_bytes(2, 'little')
    )

    # Retarget the hardcoded name-plural glyph (達 -> 等).  Only the immediate
    # (low 2 bytes of the instruction word) changes.
    name_plural_offset = NAME_PLURAL_INSTRUCTION_OFFSET
    actual_instruction = bytes(
        patched_data[name_plural_offset:name_plural_offset + 4]
    )
    if actual_instruction != ORIGINAL_NAME_PLURAL_INSTRUCTION:
        raise AssertionError(
            'Unexpected name-plural instruction at '
            f'{name_plural_offset:#x}: expected '
            f'{ORIGINAL_NAME_PLURAL_INSTRUCTION.hex()}, '
            f'got {actual_instruction.hex()}'
        )
    patched_data[name_plural_offset:name_plural_offset + 2] = (
        resolve_static_ui_glyph(NAME_PLURAL_CHARACTER).to_bytes(2, 'little')
    )

    for glyph_index, width_value in (width_table_overrides or {}).items():
        if not 0 <= glyph_index <= 0x0566:
            raise ValueError(
                f'Static width glyph index is out of range: {glyph_index:#x}'
            )
        if not 0 <= width_value <= 0xFF:
            raise ValueError(f'Invalid static width byte: {width_value:#x}')

        table_address = STATIC_WIDTH_TABLE_ADDRESS + glyph_index
        table_offset = virtual_address_to_file_offset(table_address)
        patched_data[table_offset] = width_value

    previous_patch_end = -1
    for patch in sorted(
        embedded_text_patches or (),
        key=lambda item: item["offset"],
    ):
        patch_id = patch.get("id", "<unknown>")
        offset = patch.get("offset")
        max_bytes = patch.get("max_bytes")
        data = patch.get("data")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError(f"{patch_id}: invalid embedded-text offset")
        if not isinstance(max_bytes, int) or max_bytes < 2:
            raise ValueError(f"{patch_id}: invalid embedded-text slot size")
        if not isinstance(data, bytes) or len(data) != max_bytes:
            raise ValueError(
                f"{patch_id}: embedded-text patch must exactly fill its slot"
            )

        end = offset + max_bytes
        if end > len(patched_data):
            raise ValueError(f"{patch_id}: embedded-text slot exceeds SLPM")
        if offset < previous_patch_end:
            raise ValueError(f"{patch_id}: embedded-text patches overlap")
        previous_patch_end = end

        original_slot = base_data[offset:end]
        current_slot = bytes(patched_data[offset:end])
        if current_slot != original_slot:
            raise AssertionError(
                f"{patch_id}: CN.asm unexpectedly changed the text slot"
            )
        patched_data[offset:end] = data

    patched_data = bytes(patched_data)
    if patched_data[luck_stat_offset:luck_stat_offset + 2] != simplified_luck_code:
        raise AssertionError('Luck-stat glyph-code patch verification failed')

    for glyph_index, width_value in (width_table_overrides or {}).items():
        table_offset = virtual_address_to_file_offset(
            STATIC_WIDTH_TABLE_ADDRESS + glyph_index
        )
        if patched_data[table_offset] != width_value:
            raise AssertionError('Static width-table patch verification failed')

    for patch in embedded_text_patches or ():
        offset = patch["offset"]
        end = offset + patch["max_bytes"]
        if patched_data[offset:end] != patch["data"]:
            raise AssertionError(
                f"{patch['id']}: embedded-text patch verification failed"
            )

    for patch in instruction_patches or ():
        offset = patch["offset"]
        end = offset + len(patch["data"])
        if patched_data[offset:end] != patch["data"]:
            raise AssertionError(
                f"{patch['id']}: instruction patch verification failed"
            )

    changed_bytes = sum(
        old != new for old, new in zip(base_data, patched_data)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(patched_data)

    print(f'Base SHA-256: {base_hash}')
    print(f'Patched SHA-256: {sha256(patched_data)}')
    print(f'Changed bytes: {changed_bytes}')
    print(f'Output: {output_path}')
    return patched_data


if __name__ == '__main__':
    patch_executable()
