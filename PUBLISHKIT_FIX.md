# PUBLISHKIT 第三轮返工（审核方独立核验 @2ccbe349，2026-10-12）— 不通过

已确认通过、**不要改坏**：白板两主题（topic_a 无品牌 / topic_b「极客视界」）真渲染、内容取自旁白、无 "Beat N"/"Your Brand"；
横竖版 ffprobe/sha256 与 DONE 一致、音轨 mean≈-20dB；垃圾文件已删；pytest 47 passed；3O lint = 基线 4 项；AGPL 长行比对无实质命中。

## F1（阻断）talkcraft 样例是错配成片，发布包为错误视频生成，QA 却判通过
- `output/talkcraft_e2e/explainer/work/render.log` = `TypeError Cannot read properties of undefined (reading 'fps')`，即本项目的「复利的力量」Remotion 渲染**失败**；
  但同目录 `explainer_landscape.mp4`（60.000s，sha256 d3915e58…）画面是「Simon Talk」水印的西贝/罗永浩预制菜新闻口播，与 `timestamps.json`（10 句复利文稿，口播止于 32.08s）毫无关系；`shotbook.json` 还是带 `__TITLE__` 的白板模板。
- 结果：`publish_bundle/` 的 copy.md/fact_sources/封面全按「复利」写，封面 cover_16_9 是预制菜画面配「复利为什么被称为世界第八大奇迹」标题。
- QA 漏检：narration_end_s=32.08 而 32–60s 仍是连续人声，`trailing_silence` 却给 `within_design=true`；没有任何「文稿 ↔ 成片音频」一致性检查。
- 要求：
  1. 修好 talkcraft 渲染（或换成本仓库真实渲染、可复现的口播成片），成片必须由其 timestamps/props 生成；不得使用来历不明的样片。做不到就从 E2E 中移除该条并如实写明，不能保留错配。
  2. QA 新增硬门：(a) 口播结束后若音频仍非静音且长度 > 设计尾巴+0.5s → fail；(b) 用 faster-whisper 对成片抽 2–3 段转写，与文稿做字符相似度（如 ≥0.6），不达标 → fail（script_mismatch）。
  3. 加单测：用错配的文稿+成片（可用现有这对）断言 QA 失败。
## F2 竖版排版仍未充满画面
- topic_a/topic_b portrait 抽帧：内容卡片只占上方约 55%，下方 ~40% 空白直到字幕；机器人图标压在要点文字上（topic_b 第 2 帧「你是否好奇」被遮）。横版 topic_a 第 2 帧机器人也压住「白板讲解」小标题。
- 要求：竖版按 1080×1920 垂直分配卡片高度/字号（内容区占 ≥75% 可用高度），图标与文字不重叠；亲自抽帧确认。
## F3 封面 3:4 由横版硬裁，标题/卡片文字被左右截断（topic_b cover_3_4）；有竖版成片时 3:4 应取竖版帧。
## 通用
- 重跑 E2E，ffprobe+sha256+抽帧写入 PUBLISHKIT_DONE.md；pytest 与 lint（不得多于基线 4 项）；禁止 mock/占位/写死样片。
- 提交作者：本仓库共享 .git/config 被写成 "OMQUALITY agent"，请用 `git -c user.name="hevi-publishkit agent" -c user.email=publishkit@hevi.local commit ...`，不要修改 .git/config。
- 长任务（白板 E2E ~15min、whisper）必须 `nohup setsid ... > e2e_run.log 2>&1 &` 独立启动，并 `sleep 300` 循环轮询直到产物生成再结束会话。
