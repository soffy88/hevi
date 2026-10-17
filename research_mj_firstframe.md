# Midjourney 出图与视频首帧 速查（据用户分享教程整理，2026-10-17）

## 流程
浏览 Explore → Personalize 建 P 配置 → Create 写描述+参数 → 挑图 → Vary / Edit / 扩图 → Upscale → 下载 → Organize 存条件

## 提示词顺序
主体 → 外观/动作 → 环境 → 光线 → 画面形式与构图。每轮只改一个主要要求。

## 头像起点参数
`--ar 1:1 --v 8.2 --raw --s 75 --c 0 --sd`（Weirdness 0；P 选好配置，做基准对比时关 P）
示例：head-and-shoulders portrait of an adult East Asian woman in her late twenties, looking at the camera, relaxed friendly smile, shoulder-length dark hair, cream linen shirt, soft window light, warm neutral background, realistic skin texture, editorial portrait photography, centered composition, space around the head --ar 1:1 --v 8.2 --raw --s 75 --c 0 --sd

## 参数
- --ar 宽:高（1:1 头像 / 16:9 横向 / 9:16 竖版），只留一个
- --v 8.2；--raw 减少默认风格
- --s 0–1000 默认100（风格化，非清晰度）；--c 0–100 默认0（多样性）；--weird
- --p 个性化（--p pID 配置 / --p mID 情绪板）；--sref 风格参考，--sw 强度默认100；--iw 图片提示权重
- --seed 只固定随机起点，不锁脸
- 网页端不写 /imagine（那是 Discord 命令）；用英文 `--`

## 选图后
- 方向不对：改描述重生成
- 要相近版本：Vary Subtle；大变化：Vary Strong（脸会变）
- 只改局部：Edit → Quick Edit / Open Editor
- 要大图：Upscale Subtle/Creative（SD 1024² → 2048²）或 Run batch as HD

## 编辑
- 换衣：Change only the cream linen shirt to muted sage green linen. Keep the same face, hair, pose, light and background.
- 蒙版：Paint → Erase（Restore 恢复），或 Smart Select → Erase selection / Erase background；棋盘格才是重画区
- 扩图：Move/resize → 比例(如2:3) + Scale 缩小原图 → Extend the existing ... background above and below ... Keep ... unchanged, coherent soft window light.
- 偏了就回原图重来，别在偏离结果上叠改

## 三种图片入口
- Attach to prompt：改原图/保留人物（V8.X 人物物体参考并入 Edit Model）→ 写改什么留什么
- Style Reference：借画风（人会变）→ 写最终画面
- Image Prompts：借内容与构图 → 写最终画面

## 系列化
Moodboard（不能配 --sw/--sv）；Style Creator 产出 --sref 代码，结束会话前先保存

## 首帧要点
- 动作需要的身体和空间要留出；脸、手清楚，物体不粘连
- 首帧宽高比对齐视频
- 视频提示词重点写动作/运镜，例：镜头缓慢推近，人物自然眨眼，嘴角轻轻上扬。先简单镜头
- MJ 自带 Animate 图生视频
- 隐私：作品库可能公开，隐身需 Pro/Mega
