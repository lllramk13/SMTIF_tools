# 译文改哪里

所有译文都在 `new/data/*.json`,只改每条记录的 **`translation`** 字段。`source` 是原文,**不要动** —— 提取和校验都靠它对位。

改完直接重新构建即可,不需要额外步骤:

```powershell
Set-Location 'P:\ROMHacking\SMT IF\new'
$env:PYTHONPATH='P:\ROMHacking\SMT IF\new\vendor'
python build.py --subtitle-videos --force `
  --output '..\Game\modified\SMT_IF_CN_新版.bin' `
  --cue    '..\Game\modified\SMT_IF_CN_新版.cue'
```

---

## 五个文件

| 文件 | 条数 | 内容 | 长度限制 |
|---|---|---|---|
| **`text.json`** | 12,261 + 266 + 9 | **主线剧情、对话、事件文本** —— 绝大部分工作量在这 | 宽松(整块重新打包) |
| **`slpm_text.json`** | 388 | 主程序内嵌:地名、装备说明、行动结果、MARKER 帮助 | **`max_bytes` 硬限制** |
| **`overlay_text.json`** | 1,045 | 商店(F0049)、事件(F0092)、合成图例(F0048)等 overlay 内文本 | **`max_bytes` 硬限制** |
| **`f0098_text.json`** | 85 + 59 | 行动名、技能分类名 | **`max_bytes` 硬限制** |
| **`name_entry_characters.json`** | 16 行 | 命名键盘那 160 个汉字 | 固定 16×10 |

`text.json` 里的三个区段:

- `texts` (12,261) —— 剧情本体,按文件/块/指针编号
- `text_17` (266) —— F0017 的菜单项(「召唤仲魔」这类)
- `text_88` (9) —— F0088 存读档界面

---

## 硬限制怎么看

`slpm_text.json` / `overlay_text.json` / `f0098_text.json` 是**原地等长注入** —— 译文直接写回原文所在的字节位置,不能变长。每条记录都带 `max_bytes`:

```json
{"id": "SLPM-000E4768", "offset": "000E4768", "max_bytes": 6,
 "source": "学校", "translation": "学校"}
```

一个汉字 = **2 字节**,所以 `max_bytes: 6` 最多 3 个字。**超了构建会直接报错并告诉你哪条、超多少**,不会静默截断,放心改。

`text.json` 没有单条限制,但整块有预算,超了同样会在构建时报错。

---

## 三条必须遵守的规则

### 1. 控制码不能丢

- **`▽`** —— 等待按键(一屏结束)
- **`{大停顿}`** —— 长停顿

丢了不会报错、JSON 看着也正常,但**游戏会一路冲过去**,实际后果是把玩家直接带出房间。电脑室软盘那段和占卜师"别算了"分支就是这么坏的。

构建时有专门的审计(`src/control_code_audit.py`)会拦住"变少",**但允许变多** —— 中文一行放不下时拆成两屏、自己加一个 `▽` 是正常操作。

### 2. 占位符原样保留

`{主角}`、`{仲魔}`、`{数值0}` 这类花括号标记是引擎运行时替换的,**拼写和大小写都不能改**,也不要翻译括号里的字。

### 3. 用字必须在字库里

字库是按当前译文统计出来的。如果你用了一个**从来没出现过的字**,构建会报"字符不在码表中"。这时要重排码表:

```powershell
python tools\rearrange_codetable.py
```

然后再构建。重排是幂等的,可以随时跑。

> ⚠️ 重排会重新分配字码。**F14 静态字库容量只有 1,383 格**,新增字太多会挤爆,构建会报 `dual-context static characters exceed low slots`。真遇到了别硬来,找我们看。

---

## 不在 JSON 里的文本

这些是**图片**,不是文本,改法完全不同:

| 内容 | 位置 |
|---|---|
| 开机免责声明屏 | `work/boot/F0083C.png` → `tools/boot_screen.py import` |
| R&D LOGO 屏 | `work/boot/F0093.png`(一般不动) |
| 影片字幕 | `MP4_Subtitle/*.AVI`(已烧录进画面) |
| 「守护者」标题 | 图形,尚未定位 |

---

## 建议的分工方式

`text.json` 有 3.5 MB,多人同时改容易冲突。建议:

- **按 `id` 前缀分工** —— `id` 形如 `F0016-00000998-0000004C`,前面的 `F00xx` 就是文件号,一个人认领若干文件号
- 改完各自跑一次构建,确认没有报错再合并
- 不要重排 JSON 的键顺序或缩进,否则 diff 会炸

---

## 常见报错对照

| 报错 | 含义 | 怎么办 |
|---|---|---|
| `... exceeds ... the original slot has N` | 译文超长 | 缩短到 N 字节(汉字算 2) |
| `字符不在码表中` / `missing from codetable` | 用了新字 | 跑 `rearrange_codetable.py` |
| `dropped pause marker` | 丢了 `▽` 或 `{大停顿}` | 补回去 |
| `dual-context static characters exceed low slots` | F14 字库满了 | 减少新增字,或找我们 |
