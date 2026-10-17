# KIDSGATE 单元：幼儿动漫安全与节奏质检闸门
worktree /data/soffy/projects/hevi-kidsgate，分支 feat/kids-gate，基于 omquality r5（已通过，558da7e7）。

## 背景
先读 KIDS_ANIME_DIRECTION.md。所有动漫线的成片都必须过 kids_gate，任何一项失败就判 FAIL，不允许假通过。报告写成 JSON + HTML，标出每项失败对应的时间码。

## 检查项（都要有真实的测量实现和阈值）
1. **镜头时长**：用场景切点检测（PySceneDetect 或 ffmpeg scdet），单镜头 <2.5s 判失败，平均 <3.5s 给警告。
2. **光敏闪烁**：逐帧算相对亮度，按 WCAG 2.3.1 / Harding 规则统计每秒闪烁次数，>3 次判失败；另外检测饱和红闪。
3. **响度**：用 ffmpeg ebur128 测整体 -16±1 LUFS、真峰值 ≤ -1.5 dBTP；相邻 400ms 短时响度跳变 >10 LU（惊吓音）判失败。
4. **语速**：根据字幕 SRT 或 ASR 时间轴计算，>3.5 字/秒 判失败。
5. **字幕字号**：从渲染元数据读取，或用 OCR 检测框估算；竖屏 <56px 判失败。
6. **台词内容**：内置中文禁用词表（暴力、恐吓、贬损、危险行为、品牌名等），再加一个可选的本地 LLM 判别接口。LLM 接口没配置时只跑词表，不能报错，也不能判通过以外的结果。
7. **画面安全（可选）**：本地 CLIP 零样本识别「血/武器/恐怖」，只给警告。

## 接入
- 在 omquality 里增加 profile=kids，并注册为能力 qa.kids_gate（见 CAPABILITY_CONTRACT.md）。
- ShotSpec 或成片导出时，如果 product_line 属于 anime/kids，自动运行 kids_gate。

## 测试
用 ffmpeg 合成坏样本，每类各一个：
- 1 秒快切；
- 5Hz 黑白闪；
- 突然 +20dB 的爆音；
- 4.5 字/秒的字幕；
- 含禁用词的台词。
每个坏样本都必须被抓到；另做一个合格样本，必须通过。
其他要求：
- 删掉产物后测试必须失败；
- pytest 以 soffy 用户运行，并设置 JWT_SECRET=test-only；
- 3O lint 不新增失败项。

## 规则
- 纯 CPU；不调用付费 API；不 push；只改本 worktree；不删 worktree 外任何东西；不清理磁盘。
- /data 剩余空间 <5G 时，写 DISK_FULL_NOTE.md 并停止。
- 完成后在 KIDSGATE_DONE.md 最后一行写 DONE KIDSGATE-R1。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-kidsgate；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 KIDSGATE_DONE.md 最后一行写 DONE KIDSGATE-R1。
