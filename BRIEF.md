# hevi 看片评委与自迭代（2026-11-07）
worktree /data/soffy/projects/hevi-judge（分支 hark/video-judge，基于 8da6d735）。思路参考 https://github.com/YeJe-cpu/SeeCut（PolyForm Noncommercial：只借方法，clean-room 重写，禁止复制其代码、提示词原文、组件或字体；在 docs 写 SEECUT_ATTRIBUTION.md 说明只借鉴方法）。可 git clone --depth 1 到 /tmp/drama-repos/SeeCut 只读阅读。

## 实现 hevi/judge/
1. 视频理解后端：服务器已装 Antigravity CLI /home/soffy/.local/sgbin/agy（用户 Google AI Pro 账号，无头调用加 --dangerously-skip-permissions；先用 agy --help 弄清用法），直接把 mp4 交给 Gemini 看；回退 /snap/bin/gemini CLI；再回退：抽帧+本地指标（无模型）。后端可插拔，mock 后端供单测。
2. 硬伤检查（不靠模型也能跑的部分先做）：时长偏差、静音/无音轨、黑屏/冻帧、字幕越界/中英混杂、素材重复率、首尾帧异常；模型部分：切题、假字/假界面、画面与旁白是否对得上。
3. 两两对比评委：A/B 两版，交换位置各判一次，两次都赢才算赢，否则平局；输出结构化 JSON（胜者、理由、可执行改进项）。用一组答案已知的样片做校准（用 /data/soffy/projects/hevi-audit-1106/samples 旧版 vs /data/soffy/projects/hevi-linefix-b/samples 新版之类构造），报告一致率。
4. 自迭代循环：生成 v1 → 硬伤检查 → 把改进项转为该产线可接受的参数调整 → 生成 v2 → 两两对比，赢了才采纳；最多 3 版；记录每版改了什么。以接口 + 至少 explainer、cinematic 两条 zerolines 接入（入口在 hevi/layer4_legacy/zerolines）。
5. API：产线任务可选 judge=true；任务记录里附评委报告。

## 额度规则
开发与单测全用 mock。真实 agy 调用：校准 + 2 条线各一次完整循环，总调用 ≤40 次，记录次数和耗时。不调用付费 API，不下载 >200MB。

## 规则
只在本 worktree 改与 commit；不推送、不碰主仓库工作区、不动生产容器。卡两次就记录跳过。PROGRESS.md 逐项追加。/data/soffy/projects/hevi/.venv/bin/python -m pytest 相关测试通过。
## 输出
JUDGE_REPORT.md（中文）：实现、commit、agy 用法、校准一致率、两条线 v1→v3 迭代记录与最终 ffprobe、调用次数、仍存问题。最后一行 DONE。
