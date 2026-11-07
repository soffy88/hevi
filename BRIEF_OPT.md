# 优化 koubo_cut（hevi-koubo，hark/koubo-cut）
复核发现：人像是静态照片、嘴不动；报告称有 GitHub/维基证据截图但抽帧看不到；约 26 秒。
1. 让人像真的说话：优先复用 hevi 现有 talking_head / avatar_spokesperson 线的口型驱动（grep 仓库里的 lipsync / wav2lip / sadtalker / liveportrait 等实现，用已安装的）；都没有则至少做基于音量包络的嘴部/头部微动+眨眼，并在报告里如实写明。
2. 证据截图必须出现在成片里：编排时对提到产品/网站的句子强制插入证据镜头（全屏截图+圈注，持续 ≥2 秒），抽帧验证。
3. 时长目标 30 秒 ±10%。字幕逐词、小窗/全屏切换保留。
4. 验收 3 次：ffprobe、volumedetect、6 帧 contact sheet（samples/opt/），帧里能看到证据截图和嘴动差异。

## 通用规则
只在本 worktree 改并 commit 到当前分支（先 commit 现有未提交改动）；不推送、不碰主仓库 /data/soffy/projects/hevi 与 hevi-pubfix、不动生产容器、不往生产 API 提交。不花钱、不调用 Google Flow、不下载 >200MB。opencode 子调用须加 </dev/null。卡两次就记录跳过。测试用 /data/soffy/projects/hevi/.venv/bin/python -m pytest。PROGRESS_OPT.md 逐项追加。最后写 OPT_REPORT.md（中文：改了什么、commit、验收数据、仍存问题），末行 DONE。限时 3 小时内完成。
