# hevi 新产线：口播精剪 koubo_cut（2026-11-07）
worktree /data/soffy/projects/hevi-koubo（分支 hark/koubo-cut，基于 8da6d735）。思路参考 https://github.com/YeJe-cpu/SeeCut（PolyForm Noncommercial：只借方法，clean-room 重写，禁止复制其代码、提示词原文、组件、字体；docs 写 SEECUT_KOUBO_ATTRIBUTION.md）。可 git clone --depth 1 到 /tmp/drama-repos/SeeCut 只读。不接 HeyGen、豆包等付费服务。

## 流程
输入：一段竖屏半身口播（真人或 hevi 现有数字人/口播线产出）+ 可选截图。
1. 转写：faster-whisper 本地（复用 hevi 已有封装），逐句时间戳；去气口/口误粗剪。
2. 素材理解：逐句判断功能（观点/数据/举例/转折/号召）。
3. 找真证据：口播提到的产品/网站/数据，用 hevi/core/browser_exec.py 的浏览器截真实网页作画面证据；禁止伪造界面；截不到就用卡片/图解。
4. 设计体系：设计令牌 → 组件（标题卡、数据卡、引用卡、手绘圈注、关键词弹字、证据截图框、人像全屏/小窗切换）→ 编排决策表（句子功能→画面处理）→ 逐镜施工单 shotbook.json。
5. 渲染：HyperFrames CLI（/home/soffy/.local/bin/hyperframes，hevi/storyfilm 已有用法可参考）或 hevi 现有渲染路径；人像在全屏和小窗之间调度；字幕逐词。
6. 可选：collage B-roll 插入接口（分支 hark/collage-broll 正在开发 hevi/collage_broll，只预留接口不依赖它）。
7. 交付：成片 mp4 + 分层工程包（各轨素材 + timeline FCPXML）。
8. 接入：能力注册、/api/studio 产线 line_id=koubo_cut、CLI python -m hevi.koubo_cut run。

## 测试素材
没有真人素材时：用 hevi 的 talking_head 或 avatar_spokesperson 线本地生成一段 25 秒中文口播（题材：用 AI 剪口播的三个误区），作为输入。

## 规则
不花钱、不下载 >200MB、只在本 worktree 改与 commit；不推送、不碰主仓库工作区、不动生产容器、不往生产 API 提交。卡两次就记录跳过。PROGRESS.md 逐项追加。单测 + /data/soffy/projects/hevi/.venv/bin/python -m pytest 相关测试通过。
## 验收
同一输入跑 3 次：成功数、耗时、ffprobe 时长/分辨率/音轨、volumedetect；抽 6 帧拼 contact sheet；产物放 samples/。
## 输出
KOUBO_REPORT.md（中文）：实现、commit、3 次结果、截证据成功率、仍存问题。最后一行 DONE。
