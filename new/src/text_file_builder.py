from pathlib import Path


RESOURCE_HEADERS = {
    b"\x01\x00",
    b"\x01\x01",
    b"\x01\x02",
    b"\x02\x00",
    b"\x02\x01",
}


def _align_to_4(value):
    return (value + 3) & ~3


def scan_resource_runs(file_data):
    if not isinstance(file_data, bytes):
        raise ValueError("file_data必须是bytes")

    runs = []
    current_run = None
    start_new_run = True
    offset = 0

    while offset + 8 <= len(file_data):
        if offset & 3:
            offset += 1
            continue

        resource_type = file_data[offset:offset + 2]
        if resource_type in RESOURCE_HEADERS:
            resource_size = int.from_bytes(
                file_data[offset + 4:offset + 8],
                "little",
            )
            resource_end = offset + resource_size

            if resource_size >= 8 and resource_end <= len(file_data):
                if start_new_run or current_run is None:
                    current_run = {
                        "start": offset,
                        "resources": [],
                    }
                    runs.append(current_run)
                elif current_run["resources"]:
                    previous = current_run["resources"][-1]
                    expected_offset = _align_to_4(
                        previous["offset"] + previous["size"]
                    )
                    gap = file_data[expected_offset:offset]
                    if any(gap):
                        raise ValueError(
                            f"资源段0x{current_run['start']:X}中包含未知非零数据"
                        )

                current_run["resources"].append({
                    "offset": offset,
                    "size": resource_size,
                    "data": file_data[offset:resource_end],
                })
                start_new_run = False
                offset = resource_end
                continue

        if file_data[offset:offset + 4] == b"\x00\x00\x00\x00":
            start_new_run = True
            current_run = None

        offset += 4

    for index, run in enumerate(runs):
        if index + 1 < len(runs):
            allocation_end = runs[index + 1]["start"]
        else:
            allocation_end = len(file_data)

        final_resource = run["resources"][-1]
        used_end = _align_to_4(
            final_resource["offset"] + final_resource["size"]
        )
        trailing_data = file_data[used_end:allocation_end]
        if any(trailing_data):
            raise ValueError(
                f"资源段0x{run['start']:X}后的保留区包含未知非零数据"
            )

        run["allocation_end"] = allocation_end
        run["allocation_size"] = allocation_end - run["start"]

    return runs


def _rebuild_resource_runs(file_name, file_data, replacements):
    runs = scan_resource_runs(file_data)
    run_by_resource_offset = {}

    for run in runs:
        for resource in run["resources"]:
            run_by_resource_offset[resource["offset"]] = run

    missing_offsets = sorted(set(replacements) - set(run_by_resource_offset))
    if missing_offsets:
        formatted_offsets = ", ".join(
            f"0x{offset:X}" for offset in missing_offsets
        )
        raise ValueError(f"{file_name}: 找不到资源 {formatted_offsets}")

    affected_runs = {
        id(run): run
        for offset, run in run_by_resource_offset.items()
        if offset in replacements
    }
    output = bytearray(file_data)
    relocations = {}

    for run in affected_runs.values():
        packed_run = bytearray()

        for resource in run["resources"]:
            original_offset = resource["offset"]
            relocations[original_offset] = run["start"] + len(packed_run)
            resource_data = replacements.get(
                original_offset,
                resource["data"],
            )

            packed_run.extend(resource_data)
            padding_size = (-len(resource_data)) % 4
            packed_run.extend(b"\x00" * padding_size)

        if len(packed_run) > run["allocation_size"]:
            raise ValueError(
                f"{file_name} 0x{run['start']:X}: 重建资源段超出固定容量 "
                f"({len(packed_run)} > {run['allocation_size']})"
            )

        packed_run.extend(
            b"\x00" * (run["allocation_size"] - len(packed_run))
        )
        output[run["start"]:run["allocation_end"]] = packed_run

    return bytes(output), relocations


def _find_text_end(file_data, text_offset):
    if text_offset < 0 or text_offset + 2 > len(file_data):
        raise ValueError(f"文本偏移超出文件范围: 0x{text_offset:X}")

    for position in range(text_offset, len(file_data) - 1, 2):
        if file_data[position:position + 2] == b"\xFF\xFF":
            return position + 2

    raise ValueError(f"文本0x{text_offset:X}缺少FFFF结束符")


def _apply_static_block(file_name, file_data, block):
    block_offset = block["block_offset"]
    record_count = block["record_count"]
    new_data = block["data"]
    pointer_table_size = record_count * 4

    if block_offset < 0 or block_offset + pointer_table_size > len(file_data):
        raise ValueError(f"{file_name}: 静态文本指针表超出文件范围")

    old_pointers = [
        int.from_bytes(
            file_data[position:position + 4],
            "little",
        )
        for position in range(
            block_offset,
            block_offset + pointer_table_size,
            4,
        )
    ]
    old_text_ends = [
        _find_text_end(file_data, block_offset + pointer)
        for pointer in old_pointers
    ]
    old_region_end = max(old_text_ends)
    old_region_size = old_region_end - block_offset

    if len(new_data) > old_region_size:
        raise ValueError(
            f"{file_name} 0x{block_offset:X}: 新静态文本超出原区域 "
            f"({len(new_data)} > {old_region_size})"
        )

    output = bytearray(file_data)
    output[block_offset:block_offset + len(new_data)] = new_data

    return bytes(output), {
        "block_offset": block_offset,
        "old_region_size": old_region_size,
        "new_data_size": len(new_data),
    }


def rebuild_text_files(text_blocks, built_resources, source_directory):
    if not isinstance(text_blocks, list):
        raise ValueError("text_blocks必须是列表")
    if not isinstance(built_resources, list):
        raise ValueError("built_resources必须是列表")

    source_directory = Path(source_directory)
    resources_by_file = {}

    for resource in built_resources:
        file_name = resource["file_name"]
        block_offset = resource["block_offset"]
        resource_data = resource["data"]
        file_replacements = resources_by_file.setdefault(file_name, {})

        if block_offset in file_replacements:
            raise ValueError(
                f"{file_name}: 重复的资源替换偏移0x{block_offset:X}"
            )
        file_replacements[block_offset] = resource_data

    static_blocks_by_file = {}
    for block in text_blocks:
        if block.get("kind") == "static":
            static_blocks_by_file.setdefault(block["file_name"], []).append(block)

    affected_files = sorted(
        set(resources_by_file) | set(static_blocks_by_file)
    )
    rebuilt_files = []

    for file_name in affected_files:
        source_path = source_directory / f"{file_name}.BIN"
        if not source_path.is_file():
            raise FileNotFoundError(f"找不到原始文件: {source_path}")

        original_data = source_path.read_bytes()
        rebuilt_data = original_data
        relocations = {}
        static_patches = []

        replacements = resources_by_file.get(file_name)
        if replacements:
            rebuilt_data, relocations = _rebuild_resource_runs(
                file_name,
                rebuilt_data,
                replacements,
            )

        for block in static_blocks_by_file.get(file_name, []):
            rebuilt_data, patch_info = _apply_static_block(
                file_name,
                rebuilt_data,
                block,
            )
            static_patches.append(patch_info)

        if len(rebuilt_data) != len(original_data):
            raise AssertionError(f"{file_name}: 重建后文件长度发生变化")

        rebuilt_files.append({
            "file_name": file_name,
            "source_path": source_path,
            "original_size": len(original_data),
            "resource_relocations": relocations,
            "static_patches": static_patches,
            "data": rebuilt_data,
        })

    return rebuilt_files
