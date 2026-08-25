---
name: hevi-watch
version: "0.1.1"
description: Watch a video (URL or local path) — download, extract scene-aware frames with budget + dedup, pull a timestamped transcript, build a contact sheet, and hand the result to the agent for grounded analysis / QA / reference extraction.
argument-hint: "<video-url-or-path> [--detail balanced]"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-watch

hevi 摄入侧技能：让 agent “看懂”任意视频（URL 或本地路径）。等价于
claude-video `/watch` 的 hevi 内化版，核心引擎在 `hevi/ingest/`。

## 前置

必须在 hevi 仓库环境内执行（需要 `uv` 与 hevi venv）。先设置并校验
`HEVI_ROOT`：

```bash
HEVI_ROOT="<hevi 仓库绝对路径>"
if [ ! -f "$HEVI_ROOT/pyproject.toml" ]; then
  echo "ERROR: HEVI_ROOT 不是 hevi 仓库根" >&2
  exit 1
fi
```

## 工作流

1. 根据用户目标选择 detail 和预算；需要视觉 QA、构图或动作证据时使用
   `balanced`（必要时提高 `--budget`），只问字幕/台词时使用 `transcript`。
2. 为本次任务创建独立的输出目录，避免复用旧帧；对 URL 或本地路径使用 shell
   安全引用。
3. 执行摄入命令。命令完成后检查 `watch:` 摘要和输出目录；不要只凭命令是否
   成功就声称已看完视频。
4. 需要视觉判断时用 `Read` 打开 `contact_sheet.jpg` 和相关帧；需要逐时间点
   佐证时读取 `frames/frame_*.jpg`，结合文件名中的时间戳与转写内容回答。
   若没有生成联络表，不要假定其存在；可重新运行并加 `--contact-sheet`。
5. 最终回答区分“转写内容”和“画面观察”，引用时间戳；对未被帧覆盖的细节明确
   说明不确定性。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.watch_cli \
  <video-url-or-path> --out-dir <dir> \
  [--detail balanced] [--budget N] [--contact-sheet] [--whisper-fallback]
```

- `--detail`：`transcript`（仅转写，零帧成本）、
  `efficient`（关键帧，快）、`balanced`（场景切换，默认）、
  `token-burner`（不封顶）。
- `--budget`：帧预算；缺省按时长自动分配（约 30 秒 30 帧，超过 10 分钟
  封顶约 100 帧）。
- `--contact-sheet`：额外生成 16 帧拼图联络表，适合先做整体审片。
- URL 需要 `yt-dlp`；本地文件直通。无字幕时，只有显式提供
  `--whisper-fallback` 才使用 faster-whisper（可能耗时且需要相应依赖）。
- 输入、输出路径均应保持绝对路径或正确引用；不要覆盖用户已有结果。

## 输出与消费

- `watch:` 摘要：帧数、时长、转写首行和 notes。
- 帧：`<out-dir>/frames/frame_*.jpg`，文件名带 `t=MM:SS` 时间戳。
- 联络表：`<out-dir>/contact_sheet.jpg`。
- 转写及其他元数据保存在 `<out-dir>` 中；若需精确引用，先列出并读取实际生成
  的文件，不要臆测文件名。

消费建议：用联络表和时间戳帧做成片 QA、StylePack 参考视频拆解
（HEVI-ARCH §5.3.7）、竞品分析或素材研究。注意：抽帧是采样而非连续观看；
快速动作、画外音和短暂画面应结合转写、相邻帧或更高预算复核。