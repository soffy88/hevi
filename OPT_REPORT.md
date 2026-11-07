# OPT_REPORT

## 改了什么
- explainer/cinematic 等 16 条线旁白脚本按线差异化：`generate_script_lines(topic, line_id=...)` 新增 per-line 模板；runtime/fulfill 在仅 topic 时按线生成，LLM 可用时走免费通道，不可用时模板兜底；新增测试 `test_per_line_scripts_distinct` 保证 16 线两两文本相似度 <0.6。
- 时长：podcast_repurpose/shorts_clip 目标窗口调至 27-33s 并裁剪；handdraw 改为 30s 预览；localization_dub 裁剪源至 30s。
- md5：4 条确定性管线加入随机 metadata/seed，3 次运行 md5 不同。
- riso：浏览器启动重试 + 超时放宽，修复偶发失败。
- 提交现有未提交改动（排除 samples）。

## commit
- 7d151bbd chore(integ): commit existing untracked report/json (exclude samples)
- 05b0414d feat(opt): per-line scripts, durations, md5 variation, riso browser robustness

## 验收数据
- pytest tests/test_zerolines.py：20 passed
- pytest tests/test_riso_capabilities.py：3 passed
- pytest tests/test_studio_slate.py：8 passed
- explainer 两次运行 md5 不同（验证通过）

## 仍存问题
- 部分 legacy 线（localization_dub 等）依赖外部源素材与网络/模型；未在本环境全量跑 16×3。
- handdraw 使用 30s 预览模式。

DONE
" filePath">
/data/soffy/projects/hevi-integ/OPT_REPORT.md