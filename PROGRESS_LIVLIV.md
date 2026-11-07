# PROGRESS_LIVLIV（2026-11-07，接续上一个 agent）

- [x] 完整阅读 BRIEF.md，并审阅未提交 diff：BRIEF.md(由 judge 简报替换)、THIRD_PARTY_NOTICES、explainer engine=livliv、capabilities talking_head engine、koubo_cut pipeline livliv 分支、talking_head pipeline livliv 分支、新增 hevi/avatar_livliv/（render/audio/characters/licenses）。未丢弃，继续在其上修改。
- [x] vendor 检查：/data/soffy/vendor/livliv-player 已 clone，du=214M（>200M），characters 含 21 个 livliv 包（index.json 21 项），LICENSE/NOTICE/CREDITS 已逐一 diff -q 校验一致。
- [x] 修 audio 平滑+提前 1 帧（原为延迟 1 帧），补 render 表演（plan_performance，真实 player.expressions 选表情/动作）。
- [x] 补接入：talking_head capability character_id、koubo_cut CLI --engine/--character-id、explainer API character_id、avatar_spokesperson(studio 线）avatar_engine=livliv 槽位、.env.example LIVLIV_CHARACTERS_ENABLED（默认 true，仅限非商用注释）。
- [x] 加 tests/test_avatar_livliv.py 并跑 pytest：38 passed（hevi .venv）。
- [x] 真实验收：3 角色 32.3s 渲染 63-68s、ffprobe/volumedetect 完成；对齐 1s 窗 corr=0.952；koubo 3 次 delivered 132-153s；contact sheet 已存 samples/livliv/；wav2lip 上游 ImportError 故以静态基线对比（A=0 vs B=18，Winner=A，模型调用 0）；LIVLIV_REPORT.md 完成。
- [x] commit（见 `git log`，分支 hark/livliv-avatar）。
