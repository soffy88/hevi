# COMICNARR 返工 r3（第 2 轮独立核验 2026-10-12 08:40 CST，实看 3 条成片逐镜头抽帧）

核验对象：feat/comicnarr-3o @ 5a971e1a（基线 98e216af），E2E 产物 output/comicnarr_e2e/ 于 2026-10-12 00:07–00:31 UTC 重新出片。

## 已确认修好（不要回退）
- 三条成片 1080x1920@25fps、H.264 + AAC 44.1k 立体声、音量 mean -18.9/-19.6/-19.1 dB；sha256 与 qa.json 一致。
- `narr[:30]` 硬切已删除；manga_bw 字幕改白字黑框，清晰可读；comic_color/guofeng 字幕 56px 粗体白字黑描边，清晰。
- manga_bw 真黑白 + 网点；共享预设 `hevi/layer4_legacy/keyframe/oprim_impl/style_presets.py`（guofeng_anime 为默认）、templates.py 兼容层、docs 已写。
- QA 新增 OCR 字幕可读性 / 同镜头内 1s 运动 / 灰度门禁；story3（草船借箭, guofeng_anime）已出片。
- tests/test_comicnarr_pipeline.py + tests/test_zerolines.py 30 passed；3O lint 仍只有基线 4 项（无新增）。

## 必须修复
1. **story1 结尾两句整句丢失（内容丢失）**：规则兜底脚本 story1 共 11 句，结尾「如果你想保住桌上的水杯，最有效的办法绝不是对它发脾气。」「多给它准备抓板和漏食玩具，把桌面易碎品收起来，才能实现人猫和平共处。」在成片/SRT 中完全没有——拆句后镜头数超过 max_scenes=14 被 `break` 截掉，故事收尾（结论/建议）丢了。要求：拆句后若超过镜头上限，**不得丢句**——改为把一个原句的多个分句放进同一个镜头（同镜头内多条字幕/\N 换行），或提高上限/合并镜头，保证成片旁白拼接 == 脚本全文。加单测：长句脚本（≥11 句、多句 >30 字）经 generate_comic_script 后所有原句内容都在，场景数 ≤ max_scenes。
2. **逗号处硬拆再补「。」造成半句**：`_split_text_to_sentences` 在逗号处切开并由 `_finalize_sentence` 补句号，story1 出现语法上的半句（SRT 序号）、TTS 也按句末语调念：
   - #7「其次，高处跌落产生的声音和运动轨迹。」（只有主语）+ #8「对猫的神经系统是强烈的感官刺激。」
   - #11「第三个原因更加直接：猫咪发现，只要东西掉地。」+ #12「主人就会立刻冲过来。」
   - #13「对于一只觉得无聊的猫来说，哪怕是被你责备两句。」+ #14「也是极好的互动。」
   - story2 SRT#3「却被里胥摊派了采办之差。」同理。
   现在字幕已经支持 \N 自动换行，**不需要再为字幕宽度把一句话拆成两句**。要求：一个原句（以 。！？… 结尾）默认保持为一个镜头一条旁白；只有真需要拆镜头时，字幕保留原逗号（不得把「，」改成「。」），TTS 一次合成整句后按分句时间点切字幕，或两个镜头共用整句音频。单测：输出 narration 中不得出现原文没有的「。」（texts 模式与规则兜底模式都测）。
3. **换行孤立标点**：story1 ASS 第 9 条「这就像人类按动圆珠笔或者捏泡泡纸一样\N。」——句号单独成行。换行算法需避头（。，！？、；：」』）不能落在行首，至少带前一个字一起换行。加单测。
4. **story1 画面与句子仍大量不符**（story2/3 已明显改善）：14 镜头中约 8 个是橘猫头像/半身像，关键道具/动作缺失（按 SRT 序号）：#1「盯着杯子」无杯子；#3 杯子完好未落地；#5「肉垫拨弄笔筒」无笔筒无爪；#6「木头小玩具滑动、扑击姿势」只有猫脸；#7/#8「铅笔滚落」无铅笔；#9/#10「纸团」无；#11/#12「主人慌张跑进房间」画面无人。要求：对道具/动作类镜头，prompt 把道具和动作放最前并强化（diffusers 原生不解析 (x:1.3) 权重语法，用前置+重复关键词，或已装的 compel），主角 token 降为次要；中景/全景构图词（medium shot, full body, on desk）避免一律特写猫脸；必要时同 seed 多候选，用本地 CLIP（若共享 venv 已有 open_clip/transformers CLIP 则用，不得新装包）按 prompt 选图。重出 story1 后逐镜头核对。
5. **COMICNARR_DONE.md 未更新/不实**：仍写「每句 ≤30 字，实测 11 句」，未写明本次三条均为 `llm_channel=deterministic_rule_fallback`（Omniroute :20128 探测不可达，curl 返回 000）。请如实更新：llm 通道、共享预设路径、每条成片时长/镜头数/sha256、已知局限。

## 验收
- 重新出 story1（必须）、story2（因 #2 拆句改动需重出）、story3：1080x1920、45–75s、有音轨，qa passed。
- SRT 拼接（去掉换行）== 规则兜底脚本全文（仅允许标点不变），无原文没有的「。」，无行首孤立标点。
- 跑 tests/test_comicnarr_pipeline.py、tests/test_zerolines.py、scripts/ci/run_3o_v3_lint.py（基线 4 项不得新增）。
- 更新 qa.json / COMICNARR_DONE.md，git commit。禁止 mock，禁止新装包，禁止改 .venv，禁止付费/云 API。
