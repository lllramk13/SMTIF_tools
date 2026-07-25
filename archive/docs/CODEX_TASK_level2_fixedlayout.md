# Codex 任务：level-2 菜单串错位根治 + 两处遗留

作者：Claude（诊断+决策）。执行：Codex。日期：2026-07-23。
背景文档：`../SMT_IF_PROJECT_DOC.md` §6、§9.4。

> **进度（2026-07-23 更新）**：决策1（每块固定布局）+ 决策3（交涉选项）**已由 Claude 实现并验证**
> —— 见 `src/text_resource_builder.py::build_text_resources` 的 try `build_fixed_layout_raw_data`/
> except 回退，及 text.json 里 F0075/F0084 的 27 条超槽裁剪（备份 text.json.pre_l2trim.bak）。
> 产出 **SMT_IF_CN_test12.bin**，实测 F0084 交涉选项、F0075「これでよろしいですか」旧固定偏移
> 处解码正确、0 回归。**Codex 只需做决策2（のこりポイント，需 RE 定位）**。下面决策1/3 保留作背景。

---

## 决策 1（核心）：每块"固定内部布局优先，装不下才紧凑"

### 已确诊的根因（有实测证据，勿再重新调查）

游戏里**菜单/选项/确认类**文本，代码按**固定的资源内部偏移**读取字符串；而当前
文本管线把每个资源块**紧凑重建**（重排指针表+去重文本 blob），会**移动块内字符串
的内部偏移**。指针表虽然更新正确了，但游戏不走指针表、走固定偏移 → 读到挪位后的
错误位置 → **部分空白/半截字/显示原文**。

实测证据（test11 = SMT_IF_CN_test11.bin）：
- **F0084 恶魔交涉选项**（block 0x800）：指针表 [1] 原 0x2C8→新 0x2C4，新位置解出"很乐意"
  （正确），但**旧固定偏移 0x2C8 解出"意"**（半截）。选项在 block 0x800（175 条短选项）
  和 0xE000（191 条）。
- **F0075「これでよろしいですか」**（升级确认，指针表第 15 项，原偏移 0x63C）：新位置
  0x602 解出"确定这样可以吗？"（正确），旧偏移 0x63C 解出错位垃圾。全盘仅此 1 处（无副本）。
- 同类先例：F0040 守护灵（已用 INPLACE 单独修）、F0018 0x1F5C（已 INPLACE）。

### 为什么用"每块固定布局优先"而不是逐文件加名单

- **固定布局**（`build_fixed_layout_raw_data`：保持原指针表+每个字符串留在原内部偏移）
  对**两种读法都安全**（固定偏移读 ✓、指针表读 ✓）。
- **紧凑重建**只对"指针表读"的文件安全（对话），对"固定偏移读"的菜单会崩。
- 所以**只要装得下就该用固定布局**，这是严格更安全的。逐文件加名单是打地鼠。
- 我测过全局：11773 条记录里 **10852 条装得进原槽、仅 921 条(7.8%)超槽**，超槽集中在
  对话文件（F0084 的超槽 281 条基本在其对话块、F0077 250、F0016 213——这些是指针表读、
  紧凑无害）。菜单/选项块（短串）几乎都装得下 → 会自动走固定布局 → 修好。

### 具体改动（`src/text_resource_builder.py::build_text_resources`）

当前逻辑：只有 `(file,block) in FIXED_LAYOUT_RESOURCE_KEYS` 才走 `build_fixed_layout_raw_data`，
否则用 `block["data"]`（= text_block_builder 产出的紧凑 raw）。

改为**每块自动尝试固定布局，失败回退紧凑**：

```python
# build_text_resources 里，对每个 resource block：
raw_data = block["data"]            # 紧凑版（默认/回退）
if (file_name, block_offset) not in PASSTHROUGH_RESOURCE_KEYS:
    try:
        raw_data = build_fixed_layout_raw_data(block, original_info["raw_data"])
    except (ValueError, KeyError):
        # 记录顺序与原指针表不符 / 某串超原槽 → 回退紧凑（仅对指针表读的对话安全）
        raw_data = block["data"]
resource_data = pack_text_resource(raw_data, original_info["resource_id"])
```

注意：
- `build_fixed_layout_raw_data` 已存在（现给 F0040 用）；它内部会校验"记录顺序==原指针表
  顺序"、"每串≤原槽"，不满足就 raise —— 正好作为"能不能固定布局"的判据，直接 try/except。
- **保留 `EXACT_SIZE_RECORD_IDS`（F0018-…-00000358）特判**不动。
- **保留 F0040/F0018 的 PASSTHROUGH+INPLACE 路线不动**（它们不进 build_text_resources，
  仍走 INPLACE，已验证 OK）。此改动只影响进 build_text_resources 的普通块。
- `resource_data` 出来后仍走 §6 的 **exact-size 偏移稳定**注入（`_rebuild_resource_runs`，
  已实现，勿动）—— 两层正交：这层管**块内字符串偏移**，那层管**资源文件偏移**。

### 验证（务必做）

1. `python build.py --dry-run --unified-normal-text` 通过。
2. 构建 test 镜像，抽查 F0075/F0084：**旧固定偏移处**解出正确中文（不是半截）。示例校验脚本思路：
   `read_resource_info(F0084, 0x800)["raw_data"]`，在**原版指针表偏移 0x2C8** 处用当前
   codetable 解码应得"很乐意"；F0075 block0 在 0x63C 处应得"确定这样可以吗？"。
3. 全量资源解压不报错（scan_resource_runs + decompress_resource 遍历所有被动过的 D/F*.BIN）。
4. **实机**：进恶魔交涉看选项、升级看确认框——不再空白/半截。
5. 回归：主线对话、商店（overlay）、之前修好的卡死点都还正常。

---

## 决策 2：のこりポイント（升级"剩余点数"）—— 需要先 RE 定位

**现状**：全盘搜「のこりポイント」「のこり」「残り」**都没有明文串**（`ポイント` 只在 SLPM
0xEF2BC 的地图标记"イベント発生ポイント"里）。所以这行是**代码里动态拼接/硬编码逐字画**
的（类似六维缩写 0xE5C20 那种硬编码字码表）。

**执行**：
1. 在 DuckStation 里到升级点数分配界面，对"のこりポイント"几个字的**字库码**下写断点/内存断点，
   或反查该界面渲染函数，定位"のこり"「ポイント」的字码来源（八成是 SLPM 里一段硬编码 li/表）。
2. 找到后，用 §7 里 `resolve_static_ui_glyph` 同款做法：把硬编码的字码改成中文字的现码位
   （如"剩余点数"），或若是短串表则原地等长替换。**报回定位结果，再决定确切改法。**
3. 约束：这些字若走 F14 渲染必须 <0x567（F14 已满，可能需要挪；先定位再说）。

---

## 决策 3：恶魔交涉选项 —— 大概率已被"决策1"一并修好

交涉选项就是 F0084 的 block 0x800/0xE000，决策1 的固定布局会让它们留在原偏移 → 自动修好。
**先做决策1、实机复测交涉**；若仍有个别选项异常，再单独看那几条是否超槽（超槽的短选项需
裁剪译文到 ≤ 原槽字节）。

---

## 不要碰

- `_rebuild_resource_runs` 的 exact-size 逻辑（管资源文件偏移，已根治卡死，勿改回无条件紧凑）。
- F0040/F0018 的 PASSTHROUGH/INPLACE。
- 码表重排里已有的 pins / 静态集（物品名/队伍名/智/等）。
- executable_patch 的运/智/等补丁。
