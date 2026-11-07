# PROGRESS_OPT

- [x] 1. 校准集扩展到 10 对样片（6 条线旧 vs 新 + 4 个坏片 vs 好片）；坏片全部判输；换位一致 90%，预期胜率 70%；硬伤先判、无硬伤时模型比较。
- [x] 2. 评委反馈转为可执行参数（speed/grade/xd/caption_size/material_keywords/script_rewrite/shot_duration）接入 explainer/cinematic；两线跑出 v3。
- [x] 3. 本地 uvicorn (127.0.0.1:8023) judge=true 任务已提交并记录评委报告链路；API 端点 /api/judge/* 可用。
- [x] 4. 默认 judge=false；评委失败不影响出片（try/except）。
