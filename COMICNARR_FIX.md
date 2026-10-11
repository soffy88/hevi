# COMICNARR 返工 r2（独立核验 2026-10-11 21:35 CST，实看成片抽帧）

核验对象：feat/comicnarr-3o @ ef2c7691（基线 98e216af）。
已确认通过：两条成片 1080x1920@25fps、H.264+AAC 立体声、sha256 与 qa.json 一致；engine=sdturbo_cpu（非 fake/cloud）；关键帧确为 SD-Turbo 漫画风插画；Ken Burns 有缓慢推拉；未改 .venv site-packages；未复制 Pixelle 代码；无 mock 实现。

## 必须修复（全部做完才算交付）
1. **旁白/字幕被硬截断丢字（最严重）**：`script_planner.py` 第 173/199/242 行 `narr[:30]` 硬切。实测 22 句里 8 句断在半个词：story1 #0「…伸出一只小」#5「…强烈的感」#6「…纯粹的探索」#7「…立刻冲过」#8「…极好的互动」#10「…人猫和」；story2 #1「…采办之」#4「…奇异的促织」。TTS 也念的是半句。删除所有硬切：超长句按标点/语义拆成两句（或两个镜头），字幕超过一行宽度时自动换行（ASS \N），一个字都不能丢。加单测：所有 narration 必须以句末标点（。！？…）结尾，且拼接后等于原输入文本（texts 模式）。
2. **manga_bw 字幕完全不可见**：story2 的 ASS ComicSub 为 PrimaryColour=&H00000000（黑字）+ BorderStyle=3 + OutlineColour=&H00000000（黑框）→ 成片底部只有一条黑杠，抽帧 6/6 全部无可读字。改为黑字白框或白字黑框，确保字色与框色反差。
3. **QA 门禁加字幕可读性检查**：qa.json passed=True 没抓到 #1/#2。新增真实门禁：每个镜头中点抽帧，裁字幕区域跑本地 OCR（如 rapidocr，已在共享 venv；没有就做字幕区亮度对比度检测），OCR 文字与该句 narration 的相似度须 ≥0.6，否则 passed=False。不得新装包到 .venv。
4. **manga_bw 画面不是黑白**：story2 多个镜头大面积绿色/青色长袍。做真正的黑白漫画后处理（灰度 + 网点/阈值），或在 prompt/CFG 层确保单色；成片抽帧必须是黑白。
5. **comic_color 字幕太小**：36–40px/1080 宽在手机上几乎看不清，改为 ≥52px，粗体，描边，且不压主体（MarginV 适当）。
6. **画面与句子相符度**：story1 #0「盯着杯子」画面无杯子无桌子，只有猫脸大特写；绿色宝石/绿色圆球反复出现（SD 把 green eyes 渗到物体）。story2 #0「宫廷殿堂/官员呈送蟋蟀」画面只有一个书生。主体 prompt 里主角 tokens 不要压过场景/动作：按 visual_desc 决定是否出现主角，关键道具（杯子、桌子、蟋蟀、官员）放在 prompt 前部；去掉主角 tokens 里的 "emerald green eyes" 之类易渗色描述或降权。重出片后抽帧亲眼核对每镜头与句子对应。
7. **风格预设抽成可共用配置（用户 2026-10-11 要求）**：用户要求漫剧类默认用非写实的国风动漫/漫画风，dramakey 将与 comicnarr 共用风格预设。现在预设硬编码在 `hevi/layer4_legacy/comicnarr/oprim_impl/templates.py` 的 `COMIC_STYLES` 里（comicnarr 私有）。请：
   - 把风格预设迁到共享关键帧层，例如 `hevi/layer4_legacy/keyframe/oprim_impl/style_presets.py`（或 `hevi/layer4_legacy/keyframe/style_presets.yaml` + 加载器），对外导出 `STYLE_PRESETS` / `get_style_preset(name)`，字段至少含 style_tokens、negative_prompt、subtitle_style、bgm_mood、transition、postprocess（如 manga_bw 的灰度网点）。
   - comicnarr 的 templates.py 改为从共享模块导入（保留向后兼容名 COMIC_STYLES/get_style_template）。
   - 新增 `guofeng_anime` 预设（国风动漫/国漫插画，非写实，negative 含 photorealistic/photo/3d/realistic），并作为 comic_narration 产线默认风格；comic_color、manga_bw 保留。
   - 在 docs/KEYFRAME-ENGINE.md 写明共享预设位置与用法，供 dramakey 直接复用。不要改 hevi-dramakey 工作区。
8. **llm_channel=deterministic_rule_fallback**：先探测本地 Omniroute 免费通道（:20128）是否可用，可用则走它；不可用保留兜底，并在 DONE 里如实写明本次是规则兜底。
9. qa.json 的 motion 指标（6 个采样点相邻差 ~127）实际是跨镜头差异，不能证明 Ken Burns 运动；改为同一镜头内相隔 1s 两帧的差异（应 >0 且远小于跨镜头差），分别记录。

## 验收
- 重新出片：story1（comic_color）、story2（manga_bw）、新增 story3（guofeng_anime，例如聊斋或三国小故事），每条 45–75s、1080x1920、有音轨。
- 每条抽 6 帧 contact sheet 亲眼看：每帧字幕清晰可读且无截断、风格正确（manga_bw 为黑白）、画面对得上句子。
- 跑 tests/test_comicnarr_pipeline.py、tests/test_zerolines.py、scripts/ci/run_3o_v3_lint.py（基线 4 项 .venv 既有失败，不得新增）。
- 更新 qa.json / COMICNARR_DONE.md（如实写 llm 通道、共享预设路径），git commit。禁止 mock，禁止新装包，禁止改 .venv。
