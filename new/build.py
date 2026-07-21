import argparse
import hashlib
import shutil
from pathlib import Path

from src.disc_injector import replace_files_in_image
from src.executable_patch import patch_executable
from src.font_builder import load_codetable, render_font
from src.font_resource import build_f13
from src.static_font_resource import build_f14
from src.text_pipeline import (
    build_text_files,
    create_disc_replacements,
    summarize_text_build,
)
from src.static_text_aliases import (
    STATIC_TEXT_SECTIONS,
    build_static_text_alias_plan,
    build_static_width_overrides,
    write_alias_manifest,
)
from src.dynamic_low_code_relocation import (
    build_dynamic_low_code_relocation_plan,
)
from src.unified_normal_text_plan import build_unified_normal_text_plan
from src.slpm_text import (
    build_slpm_text_patches,
    load_slpm_text_records,
    translated_slpm_texts,
)
from src.original_ui_glyphs import load_original_ui_glyph_overrides


NEW_DIRECTORY = Path(__file__).resolve().parent
PROJECT_DIRECTORY = NEW_DIRECTORY.parent
GAME_DIRECTORY = PROJECT_DIRECTORY / "Game"
BUILD_DIRECTORY = NEW_DIRECTORY / "build"

DEFAULT_BASE_IMAGE = (
    GAME_DIRECTORY
    / "ogd"
    / "Shin Megami Tensei If... (Japan).bin"
)
DEFAULT_OUTPUT_IMAGE = (
    GAME_DIRECTORY
    / "modified"
    / "SMT_IF_CN_build.bin"
)
DEFAULT_MANIFEST = PROJECT_DIRECTORY / "extrac" / "_iso_manifest.json"
DEFAULT_CUE_PATH = DEFAULT_OUTPUT_IMAGE.with_suffix(".cue")

EXPECTED_BASE_SHA256 = (
    "03B286EC683F71AF968AF6A917D926F7F1C2A27BD1A6F3DF8D71086DFA79BCBF"
)


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest().upper()


def build_assets(
    use_static_aliases=False,
    relocate_dynamic_low_codes=False,
    use_unified_normal_text=False,
):
    BUILD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    slpm_text_records = load_slpm_text_records()
    if use_unified_normal_text and (
        use_static_aliases or relocate_dynamic_low_codes
    ):
        raise ValueError(
            "--unified-normal-text cannot be combined with the older "
            "alias/relocation plans"
        )

    normal_text_plan = None
    if use_unified_normal_text:
        normal_text_plan = build_unified_normal_text_plan(
            NEW_DIRECTORY / "data" / "codetable.json",
            NEW_DIRECTORY / "data" / "text.json",
            extra_used_texts=translated_slpm_texts(
                slpm_text_records,
                renderer="dynamic",
            ),
            extra_static_texts=translated_slpm_texts(
                slpm_text_records,
                renderer="static",
            ),
        )

    alias_plan = None
    if use_static_aliases:
        alias_plan = build_static_text_alias_plan()
        write_alias_manifest(alias_plan)

    relocation_plan = None
    if relocate_dynamic_low_codes:
        first_free_index = (
            alias_plan.highest_index + 1
            if alias_plan
            else max(load_codetable()) + 1
        )
        relocation_plan = build_dynamic_low_code_relocation_plan(
            first_free_index
        )

    width_table_overrides = build_static_width_overrides()
    if alias_plan:
        width_table_overrides.update(alias_plan.width_table_overrides)

    slpm_text_patches = ()
    if normal_text_plan:
        slpm_text_patches = build_slpm_text_patches(
            slpm_text_records,
            global_character_overrides=(
                normal_text_plan.global_character_overrides
            ),
            static_character_overrides=(
                normal_text_plan.section_character_overrides["text_17"]
            ),
        )
        print(
            "Embedded SLPM text: "
            f"{len(slpm_text_patches)}/{len(slpm_text_records)} translated"
        )

    print("[1/5] Rendering dynamic/static fonts")
    glyph_overrides = {}
    if normal_text_plan:
        glyph_overrides.update(normal_text_plan.font_overrides)
    if alias_plan:
        glyph_overrides.update(alias_plan.font_overrides)
    if relocation_plan:
        glyph_overrides.update(relocation_plan.font_overrides)
    f13_font_path = BUILD_DIRECTORY / "font_f13_1bpp.bin"
    f14_font_path = BUILD_DIRECTORY / "font_f14_1bpp.bin"
    f13_glyph_overrides = dict(glyph_overrides)
    f13_glyph_overrides.update(load_original_ui_glyph_overrides())

    render_font(
        output_path=f13_font_path,
        preview_path=BUILD_DIRECTORY / "font_f13_preview.png",
        glyph_overrides=f13_glyph_overrides,
    )
    render_font(
        output_path=f14_font_path,
        preview_path=BUILD_DIRECTORY / "font_f14_preview.png",
        glyph_overrides=(glyph_overrides or None),
    )

    print("[2/5] Building F0013 dynamic font resource")
    f13_data = build_f13(raw_font_path=f13_font_path)

    print("[3/5] Building F0014 static font resource")
    f14_data = build_f14(raw_font_path=f14_font_path)

    print("[4/5] Applying executable patch")
    executable_data = patch_executable(
        width_table_overrides=width_table_overrides,
        embedded_text_patches=slpm_text_patches,
    )

    print("[5/5] Building translated text files")
    if normal_text_plan:
        character_code_overrides = dict(
            normal_text_plan.global_character_overrides
        )
        section_character_code_overrides = {
            section: dict(overrides)
            for section, overrides
            in normal_text_plan.section_character_overrides.items()
        }
    else:
        character_code_overrides = {}
        if alias_plan:
            character_code_overrides.update(
                alias_plan.global_character_overrides
            )
        if relocation_plan:
            character_code_overrides.update(
                relocation_plan.character_code_overrides
            )

        section_character_code_overrides = {}
        if alias_plan:
            for section, overrides in alias_plan.section_character_overrides.items():
                section_character_code_overrides[section] = dict(overrides)
        if relocation_plan:
            for section in STATIC_TEXT_SECTIONS:
                section_overrides = section_character_code_overrides.setdefault(
                    section, {}
                )
                section_overrides.update(
                    relocation_plan.static_character_code_overrides
                )

    text_result = build_text_files(
        character_code_overrides=(character_code_overrides or None),
        section_character_code_overrides=(
            section_character_code_overrides or None
        ),
    )
    replacements = create_disc_replacements(text_result)

    if "D/F0013.BIN" in replacements:
        raise ValueError("文本替换列表不应包含F0013.BIN")
    if "D/F0014.BIN" in replacements:
        raise ValueError("Text replacements must not contain F0014.BIN")
    if "SLPM_871.54" in replacements:
        raise ValueError("文本替换列表不应包含SLPM_871.54")

    replacements["D/F0013.BIN"] = f13_data
    replacements["D/F0014.BIN"] = f14_data
    replacements["SLPM_871.54"] = executable_data

    return {
        "alias_plan": alias_plan,
        "relocation_plan": relocation_plan,
        "normal_text_plan": normal_text_plan,
        "slpm_text_records": slpm_text_records,
        "slpm_text_patches": slpm_text_patches,
        "text_result": text_result,
        "replacements": replacements,
    }


def write_cue(cue_path, image_path):
    cue_path = Path(cue_path)
    image_path = Path(image_path)
    cue_text = (
        f'FILE "{image_path.name}" BINARY\n'
        "  TRACK 01 MODE2/2352\n"
        "    INDEX 01 00:00:00\n"
    )
    cue_path.write_text(cue_text, encoding="ascii", newline="\n")


def build_disc(
    base_image=DEFAULT_BASE_IMAGE,
    output_image=DEFAULT_OUTPUT_IMAGE,
    manifest_path=DEFAULT_MANIFEST,
    cue_path=None,
    force=False,
    verify_base_hash=True,
    dry_run=False,
    use_static_aliases=False,
    relocate_dynamic_low_codes=False,
    use_unified_normal_text=False,
):
    base_image = Path(base_image).resolve()
    output_image = Path(output_image).resolve()
    manifest_path = Path(manifest_path).resolve()
    cue_path = (
        Path(cue_path).resolve()
        if cue_path is not None
        else output_image.with_suffix(".cue")
    )

    if not base_image.is_file():
        raise FileNotFoundError(f"找不到基础镜像: {base_image}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到ISO清单: {manifest_path}")
    if base_image == output_image:
        raise ValueError("输出镜像不能覆盖基础镜像")

    base_hash = sha256_file(base_image)
    if verify_base_hash and base_hash != EXPECTED_BASE_SHA256:
        raise ValueError(
            f"基础镜像SHA-256不匹配: {base_hash}; "
            f"应为 {EXPECTED_BASE_SHA256}"
        )

    assets = build_assets(
        use_static_aliases=use_static_aliases,
        relocate_dynamic_low_codes=relocate_dynamic_low_codes,
        use_unified_normal_text=use_unified_normal_text,
    )
    text_summary = summarize_text_build(assets["text_result"])
    replacements = assets["replacements"]

    print("Text summary:", text_summary)
    print("Disc files prepared:", len(replacements))

    if dry_run:
        print("Dry-run complete; disc image was not created")
        return {
            "base_hash": base_hash,
            "text_summary": text_summary,
            "replacement_count": len(replacements),
            "output_image": None,
            "output_hash": None,
        }

    if output_image.exists() and not force:
        raise FileExistsError(
            f"输出镜像已存在: {output_image}; 使用 --force 允许覆盖"
        )

    output_image.parent.mkdir(parents=True, exist_ok=True)
    temporary_image = output_image.with_name(output_image.name + ".tmp")
    temporary_image.unlink(missing_ok=True)

    try:
        print("Copying clean base image")
        shutil.copyfile(base_image, temporary_image)

        print("Injecting files and rebuilding EDC/ECC")
        injection_summary = replace_files_in_image(
            temporary_image,
            manifest_path,
            replacements,
        )

        if temporary_image.stat().st_size != base_image.stat().st_size:
            raise AssertionError("构建后镜像长度发生变化")

        if output_image.exists():
            output_image.unlink()
        temporary_image.replace(output_image)
    except Exception:
        temporary_image.unlink(missing_ok=True)
        raise

    write_cue(cue_path, output_image)
    output_hash = sha256_file(output_image)

    print("Build complete")
    print("Image:", output_image)
    print("CUE:", cue_path)
    print("SHA-256:", output_hash)

    return {
        "base_hash": base_hash,
        "text_summary": text_summary,
        "replacement_count": len(replacements),
        "injection_summary": injection_summary,
        "output_image": output_image,
        "output_hash": output_hash,
    }


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Build the complete SMT If Chinese translation image."
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE_IMAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_IMAGE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cue", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-base-hash", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--static-aliases",
        action="store_true",
        help="Enable the experimental low-code static-text alias plan.",
    )
    parser.add_argument(
        "--relocate-dynamic-low-codes",
        action="store_true",
        help=(
            "Move original UI/name-range codes to high F13 copies for "
            "normal dialogue while preserving their low F14 glyphs."
        ),
    )
    parser.add_argument(
        "--unified-normal-text",
        action="store_true",
        help=(
            "Use the unified safe code layout for normal/static translated "
            "text without replacing low name/UI glyphs."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    build_disc(
        base_image=arguments.base,
        output_image=arguments.output,
        manifest_path=arguments.manifest,
        cue_path=arguments.cue,
        force=arguments.force,
        verify_base_hash=not arguments.skip_base_hash,
        dry_run=arguments.dry_run,
        use_static_aliases=arguments.static_aliases,
        relocate_dynamic_low_codes=arguments.relocate_dynamic_low_codes,
        use_unified_normal_text=arguments.unified_normal_text,
    )
