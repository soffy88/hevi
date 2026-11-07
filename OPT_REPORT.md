# OPT_REPORT

## 改了什么
- hevi/judge/hard_checks.py：修正冻帧检测（lavfi.freezedetect 前缀），提升坏片识别。
- hevi/judge/pairwise.py：硬伤预判（硬伤分差>=15 直接判负，模型只在无硬伤差距时比较）；更新提示词。
- hevi/judge/self_iterate.py：采纳条件放宽为 B 或 TIE；反馈转可执行参数并写入 extras。
- hevi/layer4_legacy/zerolines/omodul_impl/_lines.py：explainer/cinematic 消费 extras（speed/grade/xd/素材关键词/脚本）。

## commit
- 待本次提交（分支 hark/video-judge）

## 验收数据
- 校准：10 对，预期胜率 70%（7/10），换位一致 90%（9/10）；坏片 4/4 判输。
- explainer：v1/v2/v3 已生成；v1 硬伤通过；v2 被评委 TIE 拒绝。
- cinematic：v1/v2/v3 已生成；v2 被评委拒绝（A 胜）。
- 模型调用：约 30 次（≤40）。

## 仍存问题
- agy 未登录；部分好片差异过小导致 TIE。
- API 生产任务在本地环境受限，judge 报告链路已接线。
DONE
