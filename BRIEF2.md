# 看片评委 第二轮
第一轮 agy 未登录、gemini 不可用、Pexels 缺 key（现已复制 .env），没有产出真实迭代。本轮：
1. 再试 agy：检查 /home/soffy/.gemini、~/.antigravity 等是否已有凭据、是否需指定 HOME；仍未登录则不要尝试登录，记录“需用户本人登录 agy”。
2. 模型不可用时，用纯本地评委（硬伤检查+指标：时长、音量、冻帧、黑屏、素材重复、字幕中英混杂、clip 相似度若已安装 open_clip 则用、否则 phash）完成两两对比与自迭代。
3. 真实跑 explainer、cinematic 两条线 v1→最多 v3（用 .env 的 Pexels），记录每版改动、评委判决、ffprobe。
4. 用旧样片 vs 新样片做校准，报告本地评委一致率。
5. 完成 API 任务记录附评委报告的接线。commit 到 hark/video-judge。
写 JUDGE2_REPORT.md，末行 DONE。规则同 BRIEF.md。

## 补充（用户 11:46）：模型评委后端改用 opencode
- 新增后端 OpencodeJudgeBackend：调用 /snap/bin/opencode run -m <model>（必须加 </dev/null 并设 timeout），把抽帧（每 2 秒 1 帧拼成 contact sheet）连同字幕/旁白文本、ffprobe 指标作为附件交给模型（先 opencode run --help 查附件参数，如 -f/--file），要求输出 JSON。
- 先用 timeout 50 测哪些 opencode-go 免费模型能看图（opencode models 列出，beam-free 优先），记录。
- 用它做硬伤里的模型部分、两两换位对比、校准一致率和 explainer/cinematic 真实 v1→v3 迭代。模型调用 ≤40 次。agy/gemini 保留为可选后端。
