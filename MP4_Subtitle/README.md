# 字幕影片重新植入

本目录中的 `Fxxxx*.AVI` 是已经烧录中文字幕的 320x240、15 fps、无音轨影片。
它们不能直接替换原盘文件；构建脚本会用 jPSXdec 将每一帧重新编码为 PS1 MDEC，
写回对应的 `extrac/D/Fxxxx.BIN` 容器副本，并保持文件长度和帧数不变。

仅准备/验证影片容器：

```powershell
Set-Location 'P:\ROMHacking\SMT IF\new'
python tools\prepare_subtitle_videos.py
```

连同中文文本、字库和字幕影片一起构建镜像：

```powershell
$env:PYTHONPATH='P:\ROMHacking\SMT IF\new\vendor'
python build.py `
  --unified-normal-text `
  --subtitle-videos `
  --output '..\Game\modified\SMT_IF_CN_with_subtitles.bin' `
  --cue '..\Game\modified\SMT_IF_CN_with_subtitles.cue'
```

已编码容器缓存在 `new/build/subtitle_videos`。AVI、原版 BIN 或 jPSXdec 改变时会自动重建；
也可用 `--rebuild-subtitle-videos` 强制重编码。若 jPSXdec 不在默认位置，使用
`--jpsxdec-jar <路径>`。
