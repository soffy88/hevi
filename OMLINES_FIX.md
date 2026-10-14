# OMLINES 返工 r6（2026-10-11 13:40 UTC 独立核验，基于 b8901c0b）

已核实通过的部分（不要回退）：13 个 MP4 的 ffprobe 时长/分辨率/音轨与 sha256 全部与 e2e_results.json 一致；mean_volume -18.7~-23 dB 非静音；localization_dub 音轨经 whisper 自动识别为中文配音；AGPL 抽查 0 命中；无付费 key；3O lint 仍是基线 4 项 .venv 失败。

不合格项（必须全部修完）：

1. **零成本档无视输入（核心问题）**：`hevi/layer4_legacy/omlines/omodul_impl/lines.py` 的 13 个 `_<line>()` 不读任何 slots；`fallback.py` 调 `LINES[line](output_dir=...)` 时 topic / source / media_path / image_path / manuscript / source_text / transcript 全部丢弃。结果是不论用户要什么，都返回写死的 Apollo 14 / 北京人 / 社区图书馆 演示片（例：E2E 给 talking_head 传了 Michio Kaku.jpg 和 topic，成片却是"北京人"卡通主播）。这等于用固定样片冒充产线。要求：
   - `omlines_fallback_workflow` 把 slots 传进每条线；每条线的文案/旁白/字幕/素材检索词由 slots 驱动（topic→LLM 不可用时用本地模板生成脚本即可，但必须含 topic 关键词；source/media_path 必须是实际处理的源；image_path 必须出现在 talking_head/avatar 画面中，例如做成 2D 主播头像/画中画）。
   - 缺必需输入时返回 failed 并说明缺什么，不得静默用内置样片。
   - E2E：每条线至少跑 2 组不同输入（例如 topic A=「长城修建史」、topic B=「咖啡的起源」；不同 media 源），contact sheet 证明两组画面/字幕不同且与各自 topic 相符；结果写入 e2e_results.json（含 input slots 摘要）。
2. **veya.py 兜底伪造质检字段**：`hevi/studio/veya.py` 两处 fallback 写死 `fulfill={"artifact_verification":{"verified":True},"quality":{"passed":True}}`，且 product 写死为 "情绪读书视频"/"历史场景"。改为填入 `zl.qa()` 的真实结果，product 用 `rec.product`/产线真实名称。
3. **localization_dub 写死翻译字典**：`_translate_en_to_zh` 里对这段 Apollo 源的逐句硬编码 mapping 删除；MyMemory 失败时要么改用另一个免费/本地方案（如本地 argos-translate / opus-mt），要么让该线 FAIL，禁止静默返回英文原文后用中文 TTS 念。provenance 必须记录实际使用的翻译器。另：`output/om_lines_e2e/localization_dub/video_localization_report.json` 是一次失败运行（translate.google.com 超时）的残留，与 SUCCESS 矛盾，重跑后清掉或更新。
4. **测试过弱**：`tests/test_omlines_e2e.py` 只断言 status/artifact 非空。增加：ffprobe 时长>0+有音轨、`zl.qa()` pass、输入相关性断言（字幕/record 中含 topic 关键词，或 talking_head 画面使用了 image_path）；并加一个"缺输入 → failed"的单元测试。talking_head 用例在负载下 >15 分钟未完成，请缩短（较短脚本/低分辨率测试档）。
5. **工作区不干净**：`hevi-remotion/public/runs/documentary_montage/audio/cue-2..5.mp3` 已提交但工作区被删除（未提交）。要么恢复，要么从 git 移除并改为运行时生成（产物不要入库），保证 `git status` 干净。
6. **DONE 报告描述与画面不符**：documentary_montage 实际 6 帧为倒计时电视画面、点火、黑白升空，没有"指挥大厅/Pad 39A 远景"；talking_head 无"名牌/大幅摇头"；avatar_spokesperson 是圆形头像角标卡通，不是"全身/半身数字人手势"。DONE 只写亲眼可见的内容。
7. 完成后：13 条全量重跑（每条 2 组输入），逐个 ffprobe+sha256+contact sheet 自己 read 看，更新 OMLINES_DONE.md，`scripts/ci/run_3o_v3_lint.py` 新失败数 0，git commit。禁止 mock、禁止付费 API、禁止放宽 QA 阈值。
