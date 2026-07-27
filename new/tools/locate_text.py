#!/usr/bin/env python3
"""
从屏幕上看到的文字，反查本项目中需要编辑的 JSON 记录。

常用命令（在 new/ 目录运行）：

  python tools/locate_text.py "落下雷电"
  python tools/locate_text.py find "地图" --dataset text
  python tools/locate_text.py todo --dataset overlay --limit 40
  python tools/locate_text.py stats

这个工具只读，不会修改翻译或游戏文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


NEW_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = NEW_DIR / "data"
SLPM_LOAD_ADDRESS = 0x8000F800


@dataclass(frozen=True)
class Dataset:
    name: str
    json_name: str


@dataclass(frozen=True)
class TextRecord:
    dataset: Dataset
    section: str
    record: dict

    @property
    def record_id(self) -> str:
        return str(self.record.get("id", "（无 ID）"))

    @property
    def source(self) -> str:
        return str(self.record.get("source", ""))

    @property
    def translation(self) -> str:
        return str(self.record.get("translation", ""))

    @property
    def status(self) -> str:
        if not self.translation.strip():
            return "待翻：译文为空"
        if self.translation == self.source:
            return "需确认：译文与原文相同"
        return "已翻"

    @property
    def needs_attention(self) -> bool:
        return not self.translation.strip() or self.translation == self.source


DATASETS = (
    Dataset("text", "text.json"),
    Dataset("slpm", "slpm_text.json"),
    Dataset("overlay", "overlay_text.json"),
    Dataset("f0098", "f0098_text.json"),
)
DATASET_BY_NAME = {dataset.name: dataset for dataset in DATASETS}


def configure_console() -> None:
    # Windows 的旧控制台编码可能让正确的 UTF-8 JSON 看起来像乱码。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def load_records(selected: str = "all") -> list[TextRecord]:
    datasets = DATASETS if selected == "all" else (DATASET_BY_NAME[selected],)
    result: list[TextRecord] = []
    for dataset in datasets:
        path = DATA_DIR / dataset.json_name
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} 顶层不是对象")
        for section, rows in data.items():
            if not isinstance(rows, list):
                raise ValueError(f"{path} 的 {section} 不是记录列表")
            for record in rows:
                if not isinstance(record, dict):
                    raise ValueError(f"{path} 的 {section} 含有非对象记录")
                result.append(TextRecord(dataset, section, record))
    return result


def compact_for_search(text: str) -> str:
    """忽略换行和普通空白，方便用屏幕上的半句话反查。"""
    return re.sub(r"\s+", "", text).casefold()


def record_matches(record: TextRecord, query: str) -> bool:
    needle = compact_for_search(query)
    fields = (
        record.record_id,
        record.section,
        record.source,
        record.translation,
    )
    return any(needle in compact_for_search(field) for field in fields)


def one_line(text: str, max_chars: int = 180) -> str:
    value = text.replace("\r", "").replace("\n", r"\n")
    if len(value) > max_chars:
        return value[: max_chars - 1] + "…"
    return value


def location_lines(record: TextRecord) -> list[str]:
    row = record.record
    lines = [
        f"编辑：data/{record.dataset.json_name} -> {record.section}",
    ]
    if record.dataset.name == "text":
        resource = record.record_id.split("-", 1)[0]
        lines.append(
            "资源：D/{0}.BIN，块 0x{1}，指针槽 0x{2}".format(
                resource,
                row.get("block_offset", "?"),
                row.get("pointer_offset", "?"),
            )
        )
    elif record.dataset.name == "slpm":
        raw_offset = str(row.get("offset", "0"))
        try:
            offset = int(raw_offset, 16)
            ram_address = SLPM_LOAD_ADDRESS + offset
            lines.append(
                f"资源：SLPM_871.54，文件偏移 0x{offset:08X}，"
                f"运行时地址约 0x{ram_address:08X}"
            )
        except ValueError:
            lines.append(f"资源：SLPM_871.54，文件偏移 0x{raw_offset}")
    elif record.dataset.name == "overlay":
        lines.append(
            f"资源：D/{record.section}.BIN，文件偏移 "
            f"0x{row.get('file_offset', '?')}，槽长 {row.get('max_bytes', '?')} 字节"
        )
    elif record.dataset.name == "f0098":
        lines.append(
            f"资源：D/F0098.BIN，文件偏移 "
            f"0x{row.get('offset', '?')}，槽长 {row.get('max_bytes', '?')} 字节"
        )
    renderer = row.get("renderer")
    if renderer:
        lines.append(f"渲染路径：{renderer}")
    return lines


def print_record(record: TextRecord, index: int | None = None) -> None:
    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}{record.record_id}  [{record.status}]")
    for line in location_lines(record):
        print(f"    {line}")
    print(f"    原文：{one_line(record.source)}")
    print(f"    译文：{one_line(record.translation) if record.translation else '（空）'}")


def limited(records: list[TextRecord], limit: int, show_all: bool) -> Iterable[TextRecord]:
    return records if show_all else records[:limit]


def cmd_find(args: argparse.Namespace) -> int:
    query = args.query.strip()
    if not query:
        print("查询文字不能为空。", file=sys.stderr)
        return 2
    matches = [
        record
        for record in load_records(args.dataset)
        if record_matches(record, query)
    ]
    if args.todo_only:
        matches = [record for record in matches if record.needs_attention]
    print(f"查询：{query!r}；找到 {len(matches)} 条。")
    for index, record in enumerate(
        limited(matches, args.limit, args.all), start=1
    ):
        print()
        print_record(record, index)
    if not matches:
        print()
        print("如果屏幕上是稳定的“错汉字”而不是原文，说明它可能仍在读取原版字码。")
        print('下一步试：python tools/textscan.py rev "屏幕错字"')
    elif not args.all and len(matches) > args.limit:
        print()
        print(f"只显示前 {args.limit} 条；加 --all 可显示全部。")
    return 0


def cmd_todo(args: argparse.Namespace) -> int:
    records = [
        record
        for record in load_records(args.dataset)
        if record.needs_attention
    ]
    if args.query:
        records = [
            record for record in records if record_matches(record, args.query)
        ]
    empty_count = sum(not record.translation.strip() for record in records)
    same_count = len(records) - empty_count
    print(
        f"待检查 {len(records)} 条：空译文 {empty_count}，"
        f"原译相同 {same_count}。"
    )
    print("注意：中日写法本来相同的词也会落入“原译相同”，需要人工确认。")
    for index, record in enumerate(
        limited(records, args.limit, args.all), start=1
    ):
        print()
        print_record(record, index)
    if not args.all and len(records) > args.limit:
        print()
        print(f"只显示前 {args.limit} 条；加 --all 可显示全部。")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    header = f"{'数据集':<10}{'总数':>8}{'已翻':>8}{'空译文':>10}{'原译相同':>12}"
    print(header)
    print("-" * len(header))
    for dataset in DATASETS:
        if args.dataset != "all" and args.dataset != dataset.name:
            continue
        records = load_records(dataset.name)
        empty_count = sum(not record.translation.strip() for record in records)
        same_count = sum(
            bool(record.translation.strip())
            and record.translation == record.source
            for record in records
        )
        translated_count = len(records) - empty_count - same_count
        print(
            f"{dataset.name:<10}{len(records):>8}{translated_count:>8}"
            f"{empty_count:>10}{same_count:>12}"
        )
    print()
    print("“原译相同”是候选清单，不等于全部漏翻；例如“学校”本来就可不改。")
    return 0


def add_common_filter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset",
        choices=("all", *DATASET_BY_NAME),
        default="all",
        help="只查某类数据（默认 all）",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从屏幕文字反查本项目的翻译 JSON 记录。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser("find", help="查找原文、译文或记录 ID")
    find_parser.add_argument("query", help="屏幕上的几个连续字符，或记录 ID")
    add_common_filter(find_parser)
    find_parser.add_argument("--limit", type=int, default=20)
    find_parser.add_argument("--all", action="store_true", help="显示全部结果")
    find_parser.add_argument(
        "--todo-only",
        action="store_true",
        help="结果中只保留空译文/原译相同记录",
    )
    find_parser.set_defaults(handler=cmd_find)

    todo_parser = subparsers.add_parser("todo", help="列出待翻/待确认候选")
    todo_parser.add_argument("query", nargs="?", help="可选的文字或记录 ID 过滤")
    add_common_filter(todo_parser)
    todo_parser.add_argument("--limit", type=int, default=30)
    todo_parser.add_argument("--all", action="store_true", help="显示全部结果")
    todo_parser.set_defaults(handler=cmd_todo)

    stats_parser = subparsers.add_parser("stats", help="显示四类数据的翻译状态")
    add_common_filter(stats_parser)
    stats_parser.set_defaults(handler=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    arguments = list(sys.argv[1:] if argv is None else argv)
    # 最常用操作允许省略 find：
    #   python tools/locate_text.py "落下雷电"
    if arguments and arguments[0] not in {"find", "todo", "stats", "-h", "--help"}:
        arguments.insert(0, "find")
    parser = build_parser()
    args = parser.parse_args(arguments)
    if getattr(args, "limit", 1) < 1:
        parser.error("--limit 必须大于 0")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
