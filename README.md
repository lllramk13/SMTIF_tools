# 《真·女神转生 if...》PS1 中文化

把 PS1《真・女神転生 if...》(SLPM-87154) 汉化的工具与数据。

- `PreWork/` —— 前任"流星"的资料（勿删）
- `new/` —— 当前实现（构建入口 `build.py`、数据 `data/`、源码 `src/`、工具 `tools/`）
- `extrac/` —— 原版光盘只读提取物（基准，勿改）
- `Game/ogd/` —— **干净原版镜像**（真原盘；`Game/modified/` 里的 Japan.bin 不是原盘）
- `Game/modified/` —— 构建输出与测试镜像

## 完整技术文档见 [`SMT_IF_PROJECT_DOC.md`](SMT_IF_PROJECT_DOC.md)

包含：状态总览、构建方法、字库/码表原理、文本管线、可执行文件补丁、
**Bug 编年史（含第四阶段乱码破案 + 卡死类 exact-size 根治）**、工具用法、给接手者的速查。

## 快速构建

```powershell
Set-Location 'P:\ROMHacking\SMT IF\new'
python build.py --dry-run --unified-normal-text                 # 只验证
python build.py --unified-normal-text --output '..\Game\modified\SMT_IF_CN_xxx.bin'
```

最新测试镜像：`Game/modified/SMT_IF_CN_test11.bin`（含全部 bug 修复）。
翻译回填：编辑 `new/data/overlay_text.json` / `slpm_text.json` 的 `translation` 字段
（约束：中文编码 + 结束符 ≤ 每条的 `max_bytes`）。
