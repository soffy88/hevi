# PUBLISHKIT 第二轮返工完成报告

分支：`feat/publishkit-3o`（本 worktree，仅本地 commit，未 push）
范围：`PUBLISHKIT_FIX.md` 六条 + `PUBLISHKIT_TASK.md` 通用规则。所有数据均为实测
（ffprobe / sha256 / 抽帧目视），**无 mock、无占位、无假 gate**。

## 一、逐条对照

### 1. 白板内容改为取自旁白稿（不再模板占位）
- `hevi/layer4_legacy/whiteboard/oskill_impl/compiler.py` 的 `extract_beat_content()`：
  每个 beat 的小标题优先取 `keywords[i]`，否则从该句旁白里截取短语；要点取自旁白分句。
  `parse_storyboard()` 把 `narration` 按 `|` 拆成 beat，一 beat 一句，逐句对齐 whisper 时间戳。
- 模板占位已彻底清除：
  - `hevi-remotion-whiteboard/scene-dsl.js` `brandMark()` 在无品牌名时直接 `return 0`（不再回落
    `'Your Brand'`）；三处封面版式也改为 `if (cfg.brand && cfg.brand.name)` 才画品牌标。
  - `hevi-remotion-whiteboard/config.json` 的 `brand.name`/`slogan` 为空、水印与片尾卡 `enabled:false`。
- 品牌文字来自输入：`produce_whiteboard()` 读 `storyboard["brand"]`（或 `config["brand"]`）。
  未提供 → 水印与片尾卡全部关闭，画面里没有任何品牌条；提供 → 水印 + 片尾卡用输入的名字/
  slogan/CTA（见 topic_b 抽帧）。
- 静态扫描 `output/whiteboard_e2e/` 全文，无 `Beat 0` / `Your Brand` / `一句话说清` 命中。

### 2. 竖版原生 1080×1920 重排（不是 16:9 缩小+糊底）
- `compiler.py` 新增 `generate_portrait_scene_js()`：按 1080×1920 重新排版，卡片 100~980px 宽，
  y 从 130 铺到 1590，字号 36~60，内容充满画面、可读。
- `produce.py` 分别产出横/竖两套 `config.json` + `scenes.js`，竖版用
  `node render.js <dir> --portrait` 真渲染（viewport 1080×1920，`render.html` 的
  `setCanvas` 重设 viewBox），**不再用 boxblur 后处理横版**。
- 竖版字幕基线单独设置（`baselineX:540, baselineY:1780, safeTop:1700, fontSize:44`）。

### 3. 字幕与白板逐句同步（faster-whisper 时间戳）
- `omodul_impl/tts_asr.py`：本地 Piper 合成 → faster-whisper large-v3-turbo（CPU int8）
  词级时间戳 → `align_words_to_segments()` 把每句旁白的起始字映射成 `segmentStarts`。
- `render.js` 的 `beatsFor(info)` 用 `segmentStarts` 作为每个 beat 的绘制窗口；
  `captions.cjs` 用同一份 `wordList` 生成字幕 cue。两者共用同一时间轴。
- `produce.py` 把 `render.pen.overflow` 由上游默认 `0.35` 改为 **`0.0`**：每个 beat 的笔迹必须
  在本句旁白结束前画完，不再侵占下一句的窗口，消除“字幕已到下一条、白板还在画上一条”的滞后。
  （实测：竖版 01-body 的“自然配音”卡片从第 5 秒提前到第 4 秒出现，与字幕同拍。）

### 4. 两份不同主题旁白稿 + 亲自抽帧
- `scripts/whiteboard_e2e.py` 内置两套主题：
  - Topic A《白板讲解视频核心优势》——无品牌；
  - Topic B《大语言模型如何思考》——品牌「极客视界」。
- 每套各出 16:9 与 9:16，并把 5s/15s/25s 抽帧写入 `topic_*/frames/`。
- 已目视确认：两套主题的白板文字/图形完全不同，且随输入变化（见下方抽帧路径）。

### 5. 清理仓库垃圾
- `blender_e2e_real.py`、`v2v_e2e_real.py`、`pull_duix.sh` 已删除（`git ls-files` 无命中）。
- `produce.py` 中 “Write a dummy script.json” 已移除（`git grep` 无命中）。

### 6. 重跑 E2E + 量化数据 + lint + 测试 + commit
见下。

## 二、E2E 实测产物（`scripts/whiteboard_e2e.py`，全真实渲染）

命令：
```bash
export PATH=$HOME/.nvm/versions/node/v26.4.0/bin:$HOME/.local/bin:$PATH
.venv/bin/python scripts/whiteboard_e2e.py
```

| 产物 | 分辨率 | 时长(s) | 视频/音频 | sha256 |
|---|---|---|---|---|
| `output/whiteboard_e2e/topic_a/whiteboard_landscape.mp4` | 1920×1080 | 31.288 | h264 / aac@48000 | `0fddf8a2308e75a6baba4e15f401b63ce019d7bea76cf5e8191c74e3907d9721` |
| `output/whiteboard_e2e/topic_a/whiteboard_portrait.mp4` | 1080×1920 | 31.288 | h264 / aac@48000 | `52dd805f7e0787974adfe772b8cf65e00f1c77a4079aa8c577b0929ae5cd8d66` |
| `output/whiteboard_e2e/topic_b/whiteboard_landscape.mp4` | 1920×1080 | 41.121 | h264 / aac@48000 | `8466e7255c4a488a0904814fdfc73531f4d5488f0b26cebdc8246047fbe8c94c` |
| `output/whiteboard_e2e/topic_b/whiteboard_portrait.mp4` | 1080×1920 | 41.121 | h264 / aac@48000 | `7e599e8663dceb53762a98fa6471ca9c15cef68b9fd156f1b35e6267cc00b4cf` |

标准路径（= topic_a 的副本，便于下游）：
- `output/whiteboard_e2e/whiteboard_landscape.mp4` sha256 `0fddf8a2…d9721`
- `output/whiteboard_e2e/whiteboard_portrait.mp4` sha256 `52dd805f…8d66`

每条视频的 3 个 gate（resolution / duration≥15s / aac@48000Hz）全部 `passed:true`，
汇总见 `output/whiteboard_e2e/e2e_summary.json`（`topic_a`/`topic_b` 均 `succeeded`）。

抽帧与 contact sheet：
- `output/whiteboard_e2e/contact_sheet_landscape.jpg`（topic_a 6 帧）
- `output/whiteboard_e2e/contact_sheet_portrait.jpg`（topic_a 6 帧）
- `output/whiteboard_e2e/topic_a/frames/{landscape,portrait}_frame_{5,15,25}s.jpg`
- `output/whiteboard_e2e/topic_b/frames/{landscape,portrait}_frame_{5,15,25}s.jpg`
- 逐句字幕：`output/whiteboard_e2e/topic_a/{landscape,portrait}/字幕.srt`（13 条）

## 三、本轮代码改动
- `hevi-remotion-whiteboard/render.js`
  - 修复 mux 挂死：`apad`/`anullsrc` 是无限流，配合 `-c:v copy -shortest` 在 ffmpeg 7.x 下
    空转不退出（实测挂 3min+、97% CPU）。改为 `apad=whole_dur=<dur>` 与 `-t <dur>` 收口，
    实测 0.6s 完成。
  - 片尾卡调用 `brandEndCard(BRAND, isPortrait)`，竖版居中。
- `hevi-remotion-whiteboard/scene-dsl.js`：`brandMark()` 无品牌名返回 0；封面三版式品牌标条件化；
  `brandEndCard(brand, isPortrait)` 竖版坐标/字号。
- `hevi-remotion-whiteboard/captions.cjs`：注释更正为 faster-whisper 时间戳。
- `hevi/layer4_legacy/whiteboard/omodul_impl/produce.py`
  - `render.pen.overflow = 0.0`（逐句同步）。
  - 竖版独立 config；`node scenes.js` 传入 `WB_CONFIG_PATH`，让品牌色/字幕安全线用对应画幅配置。
- `hevi/layer4_legacy/whiteboard/oskill_impl/compiler.py`、`omodul_impl/tts_asr.py`：
  内容抽取 + whisper 逐句对齐（上一轮已落地，本轮复核）。
- `scripts/whiteboard_e2e.py`：双主题、横竖各一、抽帧、summary。

## 四、Lint 与测试
- 3O v3 lint：`scripts/ci/run_3o_v3_lint.py` → `3O_V3_LINT=FAIL`，失败 **4** 项
  （`check_no_sibling_call` / `check_omodul_signature` / `check_enabled_pillars` /
  `check_oprim_keyword_only`），与基线一致，**无新增**；失败项均为仓库既有债务，
  输出中不含 `whiteboard` 相关文件。
- 单元测试：`JWT_SECRET=testsecret .venv/bin/python -m pytest -q tests/test_whiteboard.py`
  → **9 passed**（含 `test_whiteboard_compiler_extracts_meaningful_content` 断言
  DSL 中无 `Beat 0` 且含旁白内容、`test_align_words_to_segments` 逐句时间戳、
  `whiteboard_explainer` capability）。

## 五、如何调用
```python
from hevi.layer4_legacy.whiteboard.omodul_impl.produce import produce_whiteboard
res = produce_whiteboard(storyboard, output_dir, {})
# storyboard = {"topic": ..., "brand": {...可选...},
#               "segments": [{"sceneType":"intro","narration":"句1。| 句2。","keywords":[...]}]}
```
输出 `output_dir/whiteboard_landscape.mp4`、`whiteboard_portrait.mp4`、
`contact_sheet_*.jpg`；`records[].gates` 为实测 gate。

## 六、已知问题 / 说明
- 本机 CPU-only，faster-whisper large-v3-turbo 逐条转写较慢（每条 30–60s 音频约 1–2min），
  整条 E2E（两主题 × 横竖）约 10–15min。
- 白板为“手绘逐笔”风格：卡片外框先画、标题随后出现，因此标题文字会在该句旁白内略微滞后
  （已通过 `overflow=0` 压到同句窗口内；实测横版第 15s 处“自然配音”标题与字幕“配合清晰自然的
  配音节奏”同拍出现）。
- 无品牌输入时不画任何品牌条/片尾卡，属预期行为。
