# video-talkcraft 能力内化

HEVI 内化的是 video-talkcraft 的「口播动效」方法与卡片库，而不是它的 agent 工作流或付费配音：

`口播稿 → 本地 TTS（逐句）→ CPU 字级对齐 → 语义拍 SHOTBOOK → 参数化动效卡时间线 → Remotion 渲染 → 实测门禁`

全程 CPU、本地模型、零付费调用。上游：`Vincentwei1021/video-talkcraft@4cd673d`。

## 能力边界

- 字级对齐：口播稿是真值，ASR（本地 faster-whisper large-v3-turbo，CPU int8）只提供时间。逐字 difflib 匹配，未匹配字在相邻锚点间插值；每句记录 `match_ratio`，门禁拒收低匹配句，不信任对齐结果。
- 语义拍：一句一拍；卡片入场 `lead/delay/startDelay` 锚定到该拍关键词被念出的时刻（字级同步），不是句首。
- 选卡：按场景角色（hook / definition / cards / reason / method / outro）先用结构化 props（标题、要点、术语、金句），其余句按强调族轮换；同卡不相邻，长句改用分行卡；文本按卡预算截断。
- 反 PPT：持续运动的 mesh 幕底在透明根层卡片之下；段落切换处三色扫转场；门禁实测最长冻结与冻结占比。
- 渲染：上游 workbench 的 `Main` 合成（多轨 ProjectData JSON）原样复用，960×540 舞台以 `--scale=2` 交付 1920×1080；9:16 由同片模糊底重构图（卡片为横屏原生，竖版不是重新排版）。
- 门禁（全部是测量值+阈值，写入 `record.json`）：分辨率、时长偏差、最长冻结、冻结占比、平均帧差 YDIF、黑场秒数、积分响度 LUFS、最长静音、对齐最小/平均匹配率、不同卡片数；另出 contact sheet。

## 可选数字人头像

- 默认关闭。`avatar=None` 时成片与无头像版本逐字节同路径产出。
- 开启：`render_narrated_storyboard(..., renderer="talkcraft", talkcraft_avatar={"mode": "lipsync" | "still", "image": "/path/portrait.jpg", "position": "right" | "left"})`；API `POST /api/explainer/run` 的 `renderer` + `avatar` 字段同义（avatar 只接受 renderer=talkcraft）。
- `lipsync`：Wav2Lip-GAN-96 ONNX 在 CPU 上逐帧重绘静态人像的口型（yoloface-8n 找脸），叠加呼吸/轻摆/重音点头；`still`：不加载模型，只有随音量的呼吸点头。
- 构图：16:9 右下（或左下）圆形画中画；9:16 放在舞台下方的空白带里，尺寸更大。
- 门禁：`avatar_lipsync_corr` = 嘴部区域逐帧变化与配音 RMS 的最佳滞后相关（±4 帧、3 帧平滑），阈值 ≥0.35；结果和滞后帧数写入 record.json。
- 默认人像 `hevi/layer4_legacy/talkcraft/assets/presenter_default.jpg` 为 AI 生成的虚构人物；模型文件放在 `HEVI_TALKCRAFT_AVATAR_MODELS`（默认 `/home/soffy/models/wav2lip`，不进库）。
- 许可：Wav2Lip 权重仅限研究/非商业；商用请用 `still` 模式或另行授权。

## 3O 映射

沿用 HEVI 的 Layer4 布局（与 montage/VideoAgent 相同），在原有 `compile_talkcraft_plan`（只出计划、`render_handoff` 占位）之上补齐渲染：

- `oprim`：`hevi/layer4_legacy/talkcraft/oprim_impl/sync.py` — `AlignedChar` / `SentenceTiming` / `NarrationSegment` / `Beat` / `TalkcraftPlan` / `GateMeasure` / `TalkcraftRecord`。
- `oskill`（纯算法，确定性）：`oskill_impl/align.py::align_script`、`oskill_impl/shotbook.py::plan_project`、`oskill_impl/avatar_math.py`（Wav2Lip 梅尔窗、人脸解码、构图、口型相关度）。
- `omodul`（有副作用的事务）：`omodul_impl/produce.py::produce_talkcraft`；私有工具 `_avatar.py`（数字人）、`_media.py`（Piper/ffmpeg）、`_whisper.py`（本地模型）、`_gates.py`（实测门禁）。
- HEVI 产线：`hevi/talkcraft/explainer_adapter.py` 作为注入渲染器接入 `hevi.explainer.production.render_narrated_storyboard(renderer="talkcraft")`；能力目录 `talkcraft_explainer`。
- 渲染子工程：`hevi-remotion-talkcraft/`（上游 workbench 的 Main 合成 + 127 张参数化卡 + 108 张模板卡；唯一改动是 `src/preview/Composition.tsx` 的逐片段透明根层 `__alpha`）。

## 入口

- Python：`hevi.layer4_legacy.talkcraft.omodul_impl.produce.produce_talkcraft(segments=[NarrationSegment...], output_dir=...)`。
- 解说线：`render_narrated_storyboard(storyboard, out, renderer="talkcraft")`，或环境变量 `HEVI_EXPLAINER_RENDERER=talkcraft`。
- 端到端证明：`python scripts/talkcraft_e2e.py output/talkcraft_e2e`。

## 运行依赖（本机，不进库）

- `hevi-remotion-talkcraft/`：`npm ci`（版本钉在 package.json，与上游 runtime 一致：remotion 4.0.519）。
- Piper 可执行与音色：`HEVI_TALKCRAFT_PIPER`、`HEVI_TALKCRAFT_VOICES`（默认指向 hevi-zero）。
- Whisper 模型目录：`HEVI_TALKCRAFT_WHISPER`。
- Node：`HEVI_NODE_BIN`。

## 未内化

- 上游 agent 工作流（SKILL.md 八步、审片子代理循环）、工作台编辑器 UI、Fish Audio 云配音、FireRedASR 下载、真人抠像/人脸安全区。
- 带主持人剪影占位的卡片在 HEVI 中以透明根层渲染（剪影隐藏），版面右侧为主持人预留的留白保留。

## 许可

上游为 **PolyForm Noncommercial 1.0.0**（`hevi-remotion-talkcraft/LICENSE.talkcraft`）。个人、教育、研究使用免费；**HEVI 任何商业使用需先取得原作者授权**（vincentwei1021@gmail.com）。内嵌音效授权见 `hevi-remotion-talkcraft/sfx-attribution/`。Remotion 本身另有许可条款。
