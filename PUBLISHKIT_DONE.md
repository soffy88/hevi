# PUBLISHKIT 完成报告（第二轮返工 + 额度中断后接续独立复核）

分支：`feat/publishkit-3o`（本 worktree，仅本地 commit，未 push）
范围：`PUBLISHKIT_FIX.md` 六条 + `PUBLISHKIT_TASK.md`（A 发布前套件 / B 白板产线）。
所有验收数据均为**实测**（ffprobe / sha256 / EBU R128 / 抽帧目视），**无 mock、无占位、无假 gate**。

---

## 〇、本次接续做了什么（接替因额度中断的 agent）

上一轮只做了白板（FIX 第 1–6 条）。**任务 A（发布前套件）当时是一份 stub，
上一份 DONE 报告完全没有覆盖**，本次重写并真跑：

| 问题 | 上一轮实际状态 | 本次处理 |
|---|---|---|
| 文案只有抖音一个平台 | 任务要求八平台 | 重写为八平台成套文案（主推/备选标题+正文+话题+置顶评论+B站/YouTube 章节） |
| 文案正文是 JS 源码 + `__TITLE__` | `copy.md` 正文为 `// 《__TITLE__》— …` | 文稿解析拒绝非文稿文件；正文全部由旁白稿生成 |
| 调用付费 LLM（`qwen3_dashscope`） | 违反零成本 | 默认不连任何端点；仅显式给 `ollama` provider 才走 `oprim.llm.llm_call`；降级原因写进报告 |
| 台账是占位串 | `{"sources":["规则降级，未能提取提取事实来源"]}` | 逐条登记文稿里真实出现的数字/日期/引语 + 支撑句 + 口径一致节 + 人工待补清单 |
| 无合规检查 | 缺失 | 六条红线规则检查（投资建议/私德指控/活人主语/绕行区/估算标注/结尾提问） |
| 无封面 QA | 只有一张 `cover.jpg` | 3:4 + 4:3 + 16:9 三张，**实测比例**，含缩略图可读性 |
| 交付 QA 缺响度、缺字幕越界 | 只有黑帧/静音 | 补 EBU R128 响度、A/V 结束对齐、解码校验、字幕 cue 区间校验 |
| E2E 把 mp4 当文稿 | `script_path = video_path # fallback just so it exists` | 删掉该兜底；三条真实产线各自的真实文稿 |
| 无测试 | `tests/test_publishkit.py` 不存在 | 新增 24 个单测（真实 ffmpeg 合成测试片，无 mock） |
| 输出不是 `publish_bundle/` | 4 个平铺文件 | 每条产线一个 `publish_bundle/`（11 个文件） |

E2E 首跑即抓到 **4 个真实失败**（不是靠改 gate 放水，逐个修根因）：
封面比例取整差 2px / 4:3·16:9 比例不成立；talkcraft 字幕越界 `unavailable`；
topic_b 口播区间内 1 段 6.4s 长静音；合规"结尾提问"命中。
修复后三条产线 6 项 gate 全绿。

---

## 一、白板产线（任务 B / FIX 第 1–6 条）

### FIX 逐条对照

1. **白板内容取自旁白稿**：`oskill_impl/compiler.py:extract_beat_content()` 每个 beat 的小标题取
   `keywords[i]`，要点取旁白分句；`parse_storyboard()` 按 `|` 把 narration 拆成 beat。
   `scene-dsl.js` 的 `brandMark()` 无品牌名直接 `return 0`（不再回落 `'Your Brand'`）。
   无品牌输入 → 水印/片尾卡全关，画面无品牌条。
2. **竖版原生 1080×1920**：`compiler.py:generate_portrait_scene_js()` 按 1080×1920 重新排版，
   `node render.js <dir> --portrait` 真渲染（viewport 1080×1920），**不是 16:9 缩小加糊底**。
3. **逐句同步**：`omodul_impl/tts_asr.py` 用 faster-whisper large-v3-turbo 词级时间戳 →
   `align_words_to_segments()` → 每个 beat 的绘制窗口 = 该句旁白的时间窗；
   `captions.cjs` 用同一份 `wordList` 生成字幕 cue；`produce.py` 把 `render.pen.overflow`
   由上游 0.35 改为 **0.0**，笔迹不侵占下一句窗口。
4. **两份不同主题**：`scripts/whiteboard_e2e.py` 内置 Topic A《白板讲解视频核心优势》（无品牌）
   与 Topic B《大语言模型如何思考》（品牌「极客视界」），横竖各一条，抽帧落盘。
5. **清理垃圾**：`blender_e2e_real.py` / `v2v_e2e_real.py` / `pull_duix.sh` 已删
   （`git ls-files` 无命中）；`produce.py` 的 "Write a dummy script.json" 已移除。
6. **重跑 E2E + 量化 + lint + 测试 + commit**：见下。

### 白板 E2E 实测产物（本次会话重新 ffprobe / sha256）

| 产物 | 分辨率 | 时长(s) | 视频/音频 | sha256 |
|---|---|---|---|---|
| `output/whiteboard_e2e/topic_a/whiteboard_landscape.mp4` | 1920×1080 | 31.287696 | h264 / aac@48000 | `0fddf8a2308e75a6baba4e15f401b63ce019d7bea76cf5e8191c74e3907d9721` |
| `output/whiteboard_e2e/topic_a/whiteboard_portrait.mp4` | 1080×1920 | 31.287696 | h264 / aac@48000 | `52dd805f7e0787974adfe772b8cf65e00f1c77a4079aa8c577b0929ae5cd8d66` |
| `output/whiteboard_e2e/topic_b/whiteboard_landscape.mp4` | 1920×1080 | 41.121333 | h264 / aac@48000 | `8466e7255c4a488a0904814fdfc73531f4d5488f0b26cebdc8246047fbe8c94c` |
| `output/whiteboard_e2e/topic_b/whiteboard_portrait.mp4` | 1080×1920 | 41.121333 | h264 / aac@48000 | `7e599e8663dceb53762a98fa6471ca9c15cef68b9fd156f1b35e6267cc00b4cf` |

汇总：`output/whiteboard_e2e/e2e_summary.json`（两主题均 `succeeded`）。
每条 3 个 gate（分辨率 / 时长≥15s / aac@48000Hz）全部 `passed:true`。

### 白板画面目视复核（本次会话从原始 mp4 重抽，非复用上轮 jpg）

| 抽帧 | 观察 |
|---|---|
| topic_a 横版 4s | 标题《白板讲解视频核心优势》+ 小机器人；字幕"今天我们要给大家介绍什么是白板讲解视频" |
| topic_a 横版 8s | 左卡「核心优势」+ 右卡「一目了然 / 让你一看就明白」；字幕"让你一看就明白！" |
| topic_a 横版 12/16s | 四卡版式：手绘风格 / 自然配音 / 聚焦注意 / 自动生成，卡片文字均为该 beat 旁白要点 |
| topic_a 横版 24s | 单卡「一键成片」居中，笔迹动画中；字幕"就能一键成片" |
| topic_a 竖版 8×1 联图 | **原生竖排**：标题置顶、卡片纵向堆叠、内容铺满 1080×1920、字幕贴近底部安全区 |
| topic_b 横版 10s | 标题换《大语言模型如何思考》，右上角品牌水印「极客视界」，卡「预测下一个词 / 智能涌现」 |
| topic_b 竖版 15s | 竖版「海量预训练 / 人类对齐 / 思维链推理」三卡堆叠，内容占满画面 |

→ 两套主题文字/图形完全不同且随输入变化；无 `Beat N` / `Your Brand` / 占位 slogan。

代码层扫描：`grep "Beat 0\|Your Brand\|一句话说清" hevi hevi-remotion-whiteboard scripts tests`
仅测试断言命中，源码 0 命中。

---

## 二、发布前套件（任务 A，本次重写）

### 3O 结构

```
hevi/layer4_legacy/publishkit/
  oprim_impl/contracts.py        数据契约：PlatformSpec/八平台规格、ScriptDoc、FactClaim、PublishGate…
  oskill_impl/script_doc.py      文稿解析（纯逻辑，媒体文件一律拒绝）
  oskill_impl/fact_check.py      事实核查清单与来源台账（纯逻辑）
  oskill_impl/platform_copy.py   八平台文案（纯逻辑）
  oskill_impl/compliance.py      合规三条红线（纯逻辑）
  omodul_impl/qa.py              交付 QA（ffprobe/ebur128/blackdetect/SRT/像素实测）
  omodul_impl/cover.py           封面生成与封面 QA（PIL + 仓库中文字体）
  omodul_impl/publish.py         编排 + LLM 降级 + gate 汇总
hevi/publishkit/adapter.py        外观层：generate_publish_bundle(video, script, out_dir, config)
```

### 输出（每条产线一个 bundle）

`output/publishkit_e2e/<case>/publish_bundle/`：
`copy.md`、`copy.json`、`qa_report.json`、`fact_sources.json`、`cover_qa.json`、
`compliance.json`、`cover_3_4.jpg`、`cover_4_3.jpg`、`cover_16_9.jpg` + 三张 `.thumb.jpg`。

### E2E 实测（三条真实成片 + 各自真实文稿）

`output/publishkit_e2e/e2e_summary.json` → `status: succeeded`，`case_count: 3`，`skipped: []`。

| case | 成片 | 分辨率/时长 | 音频 | 成片 sha256 |
|---|---|---|---|---|
| `talkcraft_explainer` | `output/talkcraft_e2e/explainer/explainer_landscape.mp4` | 960×540 / 60.000s | h264+aac@48000 | `d3915e587538507210a31a460b60b610c30d13f31bac77f90b40f468be3ef7ef` |
| `whiteboard_topic_a` | `output/whiteboard_e2e/topic_a/whiteboard_landscape.mp4` | 1920×1080 / 31.288s | h264+aac@48000 | `0fddf8a2…d9721` |
| `whiteboard_topic_b` | `output/whiteboard_e2e/topic_b/whiteboard_landscape.mp4` | 1920×1080 / 41.121s | h264+aac@48000 | `8466e725…8c94c` |

文稿：talkcraft 用 `work/timestamps.json`（10 句 VO 时间戳）；白板用
`landscape/scenes/script.json`（9 句 beat 旁白）。

**交付 QA 实测值**

| 项 | talkcraft_explainer | whiteboard_topic_a | whiteboard_topic_b |
|---|---|---|---|
| 响度 I / LRA / TruePeak | −16.2 LUFS / 3.3 / −1.8 dBFS | −16.6 / 3.4 / −2.9 | −16.1 / 4.0 / −2.9 |
| A/V 结束差（一帧=0.0333s） | 0.000s | 0.002s | 0.021s |
| 黑帧段 / 解码错误 | 0 / 0 | 0 / 0 | 0 / 0 |
| 字幕 cue 来源 | talkcraft timestamps | 白板 `字幕.srt` | 白板 `字幕.srt` |
| cue 数 / 有序 / 不重叠 / 末条结束 | 10 / ✓ / ✓ / 32.08s | 13 / ✓ / ✓ / 30.498s | 11 / ✓ / ✓ / 34.868s |
| 口播区间内长静音 | 0 | 0 | 0 |
| 尾静默（设计片尾卡 7.0s） | — | — | 6.391s ✓ 在设计内 |

**封面 QA（实测比例）**：三条产线各 3 张，全部精确成立
`宽×rh == 高×rw`：3:4 = **1080×1440**、4:3 = **1080×810**、16:9 = **1088×612**。

**事实台账**：talkcraft `status=unsourced, claims=4`（三个 / 第一年 / 第二年 / 三步）；
topic_b `claims=2`；topic_a `no_claims`。每条含 `claim / supports_line / script_excerpt /
source_url(空) / checked_on / note`；未人工补链接的一律 `sourced:false` 并进 `manual_todo`，
**不编造出处**。

**gate 结果（三条产线一致全绿）**

```
delivery_qa PASS | cover_ratios PASS | compliance PASS
platform_copy_complete PASS 8/8 | titles_within_limit PASS | no_placeholder_copy PASS
```

### 八平台文案样例（`copy.md`，实测输出）

- 抖音主推标题：`复利为什么被称为世界第八大奇迹，这条讲明白了`（20字 ≤30）
- 小红书主推标题：`复利为什么被称为世界第八大奇迹，一条讲清`（20字 = 上限20）
- B站：`复利为什么被称为世界第八大奇迹【极客视界】`（topic_b 给了品牌才加【】）
- B站章节用**成片实际时间戳**：`00:00 / 00:04 / 00:07 / 00:10 / 00:14 / 00:17`
- 置顶评论 = 口径说明 + 经验式提问：`…另外想问你：关于复利为什么被称为世界第八大奇迹，你会先从哪一步开始？`

---

## 三、Lint 与测试（本次会话实测）

| 项 | 结果 |
|---|---|
| `scripts/ci/run_3o_v3_lint.py` | `3O_V3_LINT=FAIL`，失败 **4** 项（`check_no_sibling_call` / `check_omodul_signature` / `check_enabled_pillars` / `check_oprim_keyword_only`） |
| 与 `lint_baseline.txt` 比对 | **整份输出逐行完全一致**（`diff` 无差异），失败项集合不变，**无新增**；失败行全部落在 `.venv/…/site-packages/oprim/`，仓库既有债务 |
| `tests/test_publishkit.py`（新增） | **24 passed**（真实 ffmpeg 合成测试片，无 mock） |
| `tests/test_whiteboard.py` | **9 passed** |
| `tests/test_publishers.py` + `test_publishers_api.py` | **14 passed** |
| `test_explainer_v6` + `test_runtime_edge_coverage` + 上述全部 | **107 passed** |
| `pytest tests/ --collect-only` | 7394 项收集，无导入错误 |

---

## 四、如何调用

### 发布前套件
```python
from hevi.publishkit.adapter import generate_publish_bundle
res = generate_publish_bundle(
    video_path=Path("output/whiteboard_e2e/topic_b/whiteboard_landscape.mp4"),
    script_path=Path("output/whiteboard_e2e/topic_b/landscape/scenes/script.json"),
    output_dir=Path("output/publishkit_e2e/whiteboard_topic_b"),
    config={"topic": "大语言模型如何思考",   # 可选：比从首句猜更准
            "brand": "极客视界",            # 可选
            "caption_cues": cues,           # 可选：SRT / VO 时间戳
            "silent_tail_s": 7.0},          # 可选：设计尾静默（片尾卡）
)
print(res.passed, res.gates)
```

### 白板产线
```python
from hevi.layer4_legacy.whiteboard.omodul_impl.produce import produce_whiteboard
res = produce_whiteboard(
    {"topic": "...", "brand": {...可选...},
     "segments": [{"sceneType": "intro", "narration": "句1。| 句2。", "keywords": [...]}]},
    Path("output/whiteboard_e2e/topic_x"), {},
)
# 输出 whiteboard_landscape.mp4 / whiteboard_portrait.mp4 / contact_sheet_*.jpg
```

### E2E
```bash
export PATH=$HOME/.local/bin:$PATH
JWT_SECRET=testsecret .venv/bin/python scripts/publishkit_e2e.py
JWT_SECRET=testsecret .venv/bin/python scripts/whiteboard_e2e.py   # 约 14 分钟（CPU whisper）
```

---

## 五、已知问题 / 说明（诚实列出）

1. **封面不是 AI 生成图**。上游 `cover-qa.md` 要求用 imagegen 生成整幅封面。本机零成本、
   无 imagegen，只能"取成片帧 + 本地中文字体排版标题"。已在 `cover_qa.json` 的
   `provenance.method = "local_frame_recompose"`、`upstream_ai_cover_rule_met = false`
   如实标注，`copy.md` 页脚也写明。**这是与上游规则的已知偏差，不是伪装通过。**
2. **来源链接需人工补**。台账只登记文稿里真实出现的数字/日期/引语及其支撑句；
   外部链接、`checked_on` 由人工按 `manual_todo` 补齐后把 `sourced` 置 true。
   本流程不联网检索，不编造出处。
3. **中文数字量词会多收**。`_CN_NUMBER` 为覆盖"三步""三个词"这类真实事实点，
   偶有过度捕获（如"一个"），宁可多收进人工复核清单，也不漏数字。
4. **talkcraft 的字幕像素扫描不参与判定**。该产线未提供字幕基线，画面下缘的深色内容
   （卡片/遮罩）与字幕无法区分，故像素扫描标 `informational=true`，
   字幕越界由 **10 条 cue 的区间校验**（有序/不重叠/不越片长）承担。
5. **口播结束点取自字幕文件末条 cue**，边界容差 0.5s 覆盖 `captions.tailSeconds=0.25`
   的字幕尾留白；容差与判定过程写在 `qa_report.json` 的 `trailing_silence`。
6. **CPU-only 环境**：faster-whisper large-v3-turbo 逐条转写慢，白板整条 E2E 约 10–15 分钟。
7. **白板手绘风格**：卡片外框先画、标题随后，同一句内标题略滞后于笔迹
   （已用 `overflow=0` 压到该句窗口内）。
8. **无品牌输入时不画任何品牌条/片尾卡**，属预期行为。

---

## 六、文件清单（本轮新增 / 重写）

**新增**
- `hevi/layer4_legacy/publishkit/oprim_impl/contracts.py`
- `hevi/layer4_legacy/publishkit/oskill_impl/{script_doc,fact_check,platform_copy,compliance}.py`
- `hevi/layer4_legacy/publishkit/omodul_impl/{qa,cover,publish}.py`
- `hevi/layer4_legacy/publishkit/{,oprim_impl/,oskill_impl/,omodul_impl/}__init__.py`
- `tests/test_publishkit.py`

**重写**
- `hevi/layer4_legacy/publishkit/omodul_impl/publish.py`（stub → 完整编排）
- `hevi/publishkit/adapter.py`
- `scripts/publishkit_e2e.py`

**上游许可**：simon-skills 为 MIT，版权与 LICENSE 保留在
`hevi-remotion-whiteboard/THIRD_PARTY_NOTICES.whiteboard.md` 与上游 `assets/fonts/OFL.txt`。