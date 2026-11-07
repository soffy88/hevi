# 优化 collage_broll（hevi-collage，hark/collage-broll）
复核发现：画面是黄底抽象色块，没有猫也没有海（不切题）；无声；没接 studio 标准接口，合入 integ 后有测试失败。
1. 切题出图：不依赖 Codex 生图。用免费路径取主体：Pexels 图片（.env 从 /data/soffy/projects/hevi/.env 复制）按隐喻卡关键词检索 → rembg/本地抠图（若已装，否则用阈值/GrabCut）→ 半调网点 + 撕纸边 + 纸纹的拼贴合成，分层视差动画；Codex 只用于写隐喻卡/visual-spec（可选）。
2. 接入 studio 标准产线接口（参照其它 zeroline 的 step/lines 约定），修好 hark/lines-integ 合入后失败的那个测试（git -C /data/soffy/projects/hevi-integ log 可看）。
3. 可选旁白：给整条线加 TTS 旁白+字幕模式（默认作为 30 秒完整片），B-roll 模式保留无声。
4. 验收：主题“橘猫看海”跑 3 次，ffprobe 时长约 30 秒、有声；抽 6 帧拼 contact sheet 存 samples/opt/，确认画面里有猫和海。

## 通用规则
只在本 worktree 改并 commit 到当前分支（先 commit 现有未提交改动）；不推送、不碰主仓库 /data/soffy/projects/hevi 与 hevi-pubfix、不动生产容器、不往生产 API 提交。不花钱、不调用 Google Flow、不下载 >200MB。opencode 子调用须加 </dev/null。卡两次就记录跳过。测试用 /data/soffy/projects/hevi/.venv/bin/python -m pytest。PROGRESS_OPT.md 逐项追加。最后写 OPT_REPORT.md（中文：改了什么、commit、验收数据、仍存问题），末行 DONE。限时 3 小时内完成。
