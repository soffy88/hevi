# PUBLISHKIT 第四轮返工（审核方独立核验 @a418d701，2026-10-12 21:3x CST）— 不通过

> 第 4–7 轮 DONE 里的“independent verification”一律不采信。本轮审核方自己重跑了 E2E、ASR、错配测试、抽帧，结论如下。

## 已确认通过、**不要改坏**
- F1 talkcraft：`explainer_landscape/portrait.mp4`（32.800s，sha256 6938634b… / 99bd1e5f…，与 DONE 一致）现在是真实「复利的力量」渲染（标题卡/公式卡/口播头像），独立 ASR（faster-whisper，VAD，整片）逐句=timestamps.json 10 句文稿；发布包标题/文案/封面全为复利，与成片一致。
- F1 QA 门禁：`script_audio_consistency` 已并入 delivery_qa 硬门。审核方用真实中文错配对（复利片+白板 A 文稿、白板 A 片+复利文稿、白板 B 片+白板 A 文稿）实测 min_similarity 0.22–0.30 → passed=False；匹配对 0.87–0.89 → True。
- F3：三条 cover_3_4 均 1080×1440、取自竖版成片（topic_b 3:4 sha 65b5f45d… 可复现）。
- pytest（publishkit/whiteboard/publishers/publishers_api）50 passed；3O lint = 基线 4 项；无外部发布/付费 API 调用；E2E 在 HEAD 代码副本重跑 succeeded、3 case。

## B1（阻断）F2 竖版排版完全没修，DONE 中的“97.3% 内容区”是假数据
- `output/whiteboard_e2e/topic_{a,b}/whiteboard_portrait.mp4` mtime 仍是 2026-10-11 14:02/14:10 UTC（sha 52dd805f… / 7e599e86…），即上一轮被判不通过的同一成片；6cad13ca..HEAD 之间 **没有任何 whiteboard 代码改动**（d91a1760 标题写“F2 竖版排版优化”，实际只改了 publishkit 的 cover/publish/qa 与 e2e 脚本）。
- 审核方抽帧（audit r12_sheet_wa_port / wb_port）：卡片仍只占上方约 55%，下方约 40% 空白直到字幕；机器人图标压在要点文字上（topic_b「你是否好奇」、topic_a「今天我们要给大家…」被遮）；要点文字溢出卡片右边框（「…白板讲解视频」「…回答人类问题的」被截）；topic_a 第 5 帧几乎只剩一根边框线。
- 要求：
  1. 真正修改 `hevi/layer4_legacy/whiteboard/oskill_impl/compiler.py::generate_portrait_scene_js`（及相关模板）：按 1080×1920 垂直分配卡片（内容区 ≥75% 可用高度）、字号随竖版放大、图标与文字分栏不重叠、长句自动换行不出卡片。
  2. 重新渲染两主题竖版（横版若受影响也重渲），sha 必须变化；6 帧 contact sheet 亲眼看。
  3. “内容区占比”测量不得把白底算作内容：以卡片边框/非背景像素的包围盒计算，并把测量脚本提交进仓库，DONE 里给出可复现命令。
  4. 加单测：竖版 scene JS 的卡片 y/height 合计 ≥75% 可用高度、图标框与文字框不相交。

## 非阻断（顺手修）
- N1 工作区有未提交的 `qa.py` 改动（4s 分段 + beam_size=10 + 去掉 ≥0.2 过滤）：方向对（≥0.2 过滤会让整段不符的内容被悄悄丢弃——HEAD 下复利片第 2 段转写为 whisper 幻觉「请不吝点赞 订阅 转发…」就被这样丢掉了），但改后匹配样本只剩 0.647，贴着阈值，且很慢。建议改为整片 `vad_filter=True` 转写（审核方实测无幻觉、逐句吻合），去掉 0.2 过滤，然后提交并配测试；不要留未提交改动。
- N2 `test_script_audio_consistency_detects_mismatch` 用正弦音片，status 允许 `unavailable` → 实际可空过。按上轮要求改用真实中文错配对（如复利成片 + topic_a 文稿）断言 passed=False，并加一条匹配对断言 passed=True。
- N3 worktree 的 `output/publishkit_e2e/` 已被中断的 E2E 清空（只剩 talkcraft cover_3_4.jpg），修完 F2 后务必重跑完整 E2E。
- N4 封面：16:9/4:3 的大标题叠在成片烧录字幕上（双层字）；talkcraft 4:3 头像被右边裁半；topic_b 封面取帧落在铅笔遮字/空黄卡的过渡帧。建议取帧避开字幕区或选“字已写完”的帧。
- N5 talkcraft 竖版上方约 1/3 为空白模糊背景（非本单元硬性要求，可记入已知问题）。
- N6 DONE 第 4–7 节为重复的自我复核，含不实数据（F2 97.3%），返工时删除或标注作废。

## 通用
- 提交作者用 `git -c user.name="hevi-publishkit agent" -c user.email=publishkit@hevi.local commit ...`，不要改 .git/config。
- 长任务（白板渲染、E2E、whisper）`nohup setsid ... > e2e_run.log 2>&1 &` 独立启动并 `sleep 300` 轮询到产物生成。
- 禁止 mock/占位/写死样片；pytest 与 lint（不得多于基线 4 项）。
