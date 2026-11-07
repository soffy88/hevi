# 优化 video-judge（hevi-judge，hark/video-judge）
复核：校准换位一致 1/2，预期“新版赢”0/2；迭代只到 v2 且被拒；judge=true 真实 API 任务未跑通。
1. 校准集扩到 ≥6 对差异明显的样片（旧审计样片 /data/soffy/projects/hevi-audit-1106 vs 新样片 /data/soffy/projects/hevi-integ 下 samples；以及刻意制造的坏片：静音、黑屏、冻帧、2 秒短片），坏片必须判输。目标换位一致 ≥80%、预期胜率 ≥80%。调提示词与本地硬伤权重：硬伤先判、模型只在无硬伤时比较。
2. 评委反馈要变成可执行参数（素材关键词、镜头时长、脚本重写指令），让 explainer/cinematic 跑出 v3 并报告评委是否认可改进。
3. 用本地 API（在 worktree 内用 uvicorn 起在 127.0.0.1 临时端口，不用生产）跑通一个 judge=true 任务，记录返回的评委报告。
4. 默认 judge=false，评委失败不影响出片。模型调用 ≤40 次。

## 通用规则
只在本 worktree 改并 commit 到当前分支（先 commit 现有未提交改动）；不推送、不碰主仓库 /data/soffy/projects/hevi 与 hevi-pubfix、不动生产容器、不往生产 API 提交。不花钱、不调用 Google Flow、不下载 >200MB。opencode 子调用须加 </dev/null。卡两次就记录跳过。测试用 /data/soffy/projects/hevi/.venv/bin/python -m pytest。PROGRESS_OPT.md 逐项追加。最后写 OPT_REPORT.md（中文：改了什么、commit、验收数据、仍存问题），末行 DONE。限时 3 小时内完成。
