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
        0x8005B2E4: bytes.fromhex('0C000724'),
        0x8005C1D0: bytes.fromhex('C0100200'),
    }
    for address, expected in expected_opcodes.items():
        offset = virtual_address_to_file_offset(address)
        actual = patched_data[offset:offset + len(expected)]
        if actual != expected:
            raise AssertionError(
                f'Patch verification failed at {address:#010x}: '
                f'expected {expected.hex()}, got {actual.hex()}'
            )

    changed_bytes = sum(
        old != new for old, new in zip(base_data, patched_data)
    )
    if changed_bytes != 155:
        raise AssertionError(
            f'Expected CN.asm to change 155 bytes, got {changed_bytes}'
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(work_output, output_path)

    print(f'Base SHA-256: {base_hash}')
    print(f'Patched SHA-256: {sha256(patched_data)}')
    print(f'Changed bytes: {changed_bytes}')
    print(f'Output: {output_path}')
    return patched_data


if __name__ == '__main__':
    patch_executable()
