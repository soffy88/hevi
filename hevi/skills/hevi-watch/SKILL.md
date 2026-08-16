---
name: hevi-watch
version: "0.1.0"
description: Watch a video (URL or local path) — download, extract scene-aware frames with budget + dedup, pull a timestamped transcript, build a contact sheet, and hand the result to the agent for grounded analysis / QA / reference extraction.
argument-hint: "<video-url-or-path> [--detail balanced]"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-watch

hevi 摄入侧技能:让 agent "看懂"任意视频(URL 或本地路径)。等价于 claude-video `/watch`
的 hevi 内化版,核心引擎在 `hevi/ingest/`。

## 前置

需要在 hevi 仓库环境内执行(有 `uv` 与 hevi venv)。设置 `HEVI_ROOT` 为 hevi 仓库根目录:

```bash
HEVI_ROOT="<hevi 仓库绝对路径>"
if [ ! -f "$HEVI_ROOT/pyproject.toml" ]; then
  echo "ERROR: HEVI_ROOT 不是 hevi 仓库根" >&2; exit 1
fi
```

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.watch_cli \
  <video-url-or-path> --out-dir <dir> [--detail balanced] [--budget N] [--contact-sheet]
```

- `--detail`:`transcript`(仅转写,零帧成本)/ `efficient`(关键帧,快)/ `balanced`(场景切换,默认)/ `token-burner`(不封顶)。
- `--budget`:帧预算;缺省按时长自动(30s→30 帧…>10min→100 帧封顶)。
- `--contact-sheet`:额外生成 16 帧拼图联络表(喂 VLM/人工审片)。
- URL 需 yt-dlp;本地文件直通。无字幕且给 `--whisper-fallback` 才走 faster-whisper。

## 输出与消费

- `watch:` 摘要(帧数/时长/转写首行/notes)。
- 帧路径在 `<out-dir>/frames/frame_*.jpg`,带 `t=MM:SS` 时间戳标记。
- 联络表在 `<out-dir>/contact_sheet.jpg`。

消费建议:verdict 成片 QA(联络表替代逐帧 VLM)、StylePack 参考视频拆解
(HEVI-ARCH §5.3.7)、竞品/素材研究。
