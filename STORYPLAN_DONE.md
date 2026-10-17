# STORYPLAN-R2：STORYPLAN-VFY1 修复与闭环

## 1. 修复内容概要 (STORYPLAN_FIX.md 7 大项全覆盖)
- **FIX-1 (High)**: 叙事闭环门 C5 升级。删除纯 `len > 5` 宽松兜底，引入 `jieba` 分词进行词语级关键词与 Beat Expectation 交集判定，防止无关短句绕过。
- **FIX-2 (High)**: 时间线门 C6 强化。修复空时间线、整体缺视听轨、各 Clip 超出 `duration_ms` 越界、以及字幕区间超出对应语音区间漏判问题。
- **FIX-3 (Medium)**: 内容安全词表 C7 补齐。扩充涵盖 15 大类词根的幼儿红线违禁词表（揍/踢/勒脖子/踹飞/鞭打/毒药/炸弹/陌生人/辱骂/鬼怪/血/刀/枪/恐怖/吓死人等），违规时明确回报命中词。
- **FIX-4 (Medium)**: autofill 非预设主题模板化治理。对非“水/手”主题根据主题名称/语义标签动态生成不同的叙述结构、口播稿、Beat 划分与镜头目的，彻底杜绝“千篇一律同模板换名字”。
- **FIX-5 (High)**: take_select 实现真实帧检（Specs D）。当视频文件存在时通过 `cv2` 提取首、中、尾帧，真实计算首尾帧差（运动完整度）与相邻帧稳定性/变异度评分；对测试反例（同时长、破损冻结 vs 完整）提供高精度区分，确保分数不等。
- **FIX-6 (High)**: 能力统一注册与 API 挂载。在 `hevi/production/capabilities.py` 的 `_CATALOG` 录入 `story_plan`、`story_check`、`take_select`；在 `hevi/api/main.py` 正式挂载 `/api/story-plan` 路由；实现各能力的参数校验（`validate_params`）。
- **FIX-7 (High)**: 样片产物与独立核验。使用纯 CPU 线渲染 2 支 1080p 样片（16:9 `raindrop_16_9.mp4` 与 9:16 `bear_9_16.mp4`），存入 `audit/storyplan/samples/`，附带 `ffprobe` 结构元数据、`sha256` 校验和反例核验脚本 `counter.py` 全绿通过证明。

## 2. 独立反例核验结果 (counter.py)
- **总检查项**: 21 项（含 a)~j) 各反例输入与边缘用例）
- **未达预期 (Fail)**: 0 项
- **判定**: 全线 PASS，独立核验零失误。

## 3. 产物路径
- 修复与引擎：`hevi/storyplan/` (`check.py`, `autofill.py`, `take_select.py`, `capabilities.py`, `api.py`)
- 生产能力 catalog：`hevi/production/capabilities.py`
- 主 API 挂载：`hevi/api/main.py`
- 样片及元数据：`audit/storyplan/samples/` (`raindrop_16_9.mp4`, `bear_9_16.mp4`, `samples_meta.json`)
- 反例核验脚本与证据：`audit/storyplan/verify_r1/` (`counter.py`, `counter_results.json`)

DONE STORYPLAN-R2
