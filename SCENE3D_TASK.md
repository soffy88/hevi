# SCENE3D 单元：Hevi 的 CPU「3D 风格化场景镜头」线（目标画面参考 littleprince.dev）

worktree：/data/soffy/projects/hevi-scene3d，分支 feat/scene3d-line，基于 7087c24a。

## 目标
做出类似 3D《小王子》网页游戏的画面：漂浮的小星球、星空粒子、被风吹动的麦田和草、卡通风格的角色或动物、暖色光和 bloom 泛光。用这条线给 Hevi 生成 9:16 和 16:9 的镜头。
约束：全程只用 CPU，不调用任何付费 API（Tripo、Meshy 等都不能用），不用 GPU。

## 技术路线
- **场景**：Three.js（npm 用 nvm 的 node）。场景由 JSON 场景描述生成，描述里写明资产、相机路径、光照、天气、时长。
- **渲染**：Playwright headless Chromium，开 `--use-angle=swiftshader --enable-unsafe-swiftshader`，走 CPU 的 WebGL。
  - 时间要确定：用 `window.__setTime(t)` 逐帧推进并截图，不能依赖 requestAnimationFrame 实时播放。
  - 截好的帧交给 ffmpeg 编码成 h264，帧率 30fps。
- **视觉要素**（至少做到这些）：
  - 球面小星球，带 toon 或 lambert 渐变着色；
  - 麦田和草用 InstancedMesh 做，顶点着色器实现风摆动；
  - 星空粒子和闪烁；
  - 雾或大气渐变；
  - UnrealBloom 泛光（CPU 太慢可以降分辨率后再放大）；
  - 柔和阴影。
- **资产**：只用 CC0 资产，例如 Kenney、Quaternius、Poly Haven；每个资产都在 ASSETS.md 里登记来源 URL 和许可证。
  - 主机直连不了 github，下载走 127.0.0.1:7890 代理、ghfast.top 或 modelscope。
  - 不允许把资产作者的工程源码 vendor 进来。
- **可选调研**：在 CPU 上做图生 3D，例如 TripoSR 或 SF3D 的开源权重，从 modelscope 下载。实测单张图出模的耗时，写进 SCENE3D_EVAL.md；超过 10 分钟就只写结论，不接入。

## 交付
1. 实现模块 hevi/layer4_legacy/scene3d/，包含场景 JSON schema、渲染器和 CLI，接口 line=scene3d 或者做成 shot 级视觉源。
2. 3 条样片，每条 10–15 秒：
   - 「小星球环绕」，16:9；
   - 「麦田里的小狐狸」，9:16；
   - 「穿过星海」，9:16，镜头推进。
   每条都要给出 sha256、时长、渲染耗时和每帧秒数，并做抽帧 contact sheet。
3. 渲染性能：1080p 下 CPU 每帧 ≤4s；做不到就先 720p 渲染再放大，并写明原因。
4. pytest 覆盖以下 4 项，3O lint 不能新增失败：
   - 同一个 seed 渲两次，帧逐字节一致；
   - 草的风动让相邻帧确实有差异，不是静帧；
   - 9:16 时主体在安全区内；
   - 删除任意一个产物，测试会失败。

## 安全规则
- 只改本 worktree，不删 worktree 外的任何文件，不清理磁盘。/data 剩余空间小于 5G 时，写 DISK_FULL_NOTE.md 并停止。
- 所有命令都设 PYTHONPATH=/data/soffy/projects/hevi-scene3d。长时间渲染用 nohup setsid 后台跑，然后轮询进度。
- node_modules 只放在本 worktree 里，不要提交。lint 日志也不要提交。
- 不 push。
- 完成后，在 SCENE3D_DONE.md 最后一行写 DONE SCENE3D-R1。

## 追加要求（2026-10-14 16:50）：能力契约
本线的能力必须按本 worktree 里的 CAPABILITY_CONTRACT.md 注册到 hevi/capabilities/registry.py，让各个产品线都能按名字调用，不要只做私有入口。如果本分支里还没有 registry.py，就按契约建一个最小实现（webkit 单元负责权威版本，最后合并时以它为准）。DONE 报告里要列出本线注册的全部能力名。

## 产品方向（2026-10-14 追加，优先级最高）
阅读 KIDS_ANIME_DIRECTION.md：Hevi 以幼儿（2–6 岁）有营养的动漫故事片为主。本单元的样片、配色、台词、节奏都要符合其中的内容要求和 kids_gate 安全闸门（镜头≥2.5s、闪烁≤3Hz、-16 LUFS、无惊吓/暴力、字幕大号）。manga 单元改为彩色绘本风为主，黑白网点只作可选项；E2E 剧情改成幼儿向。huobao 增加 kids 模式（剧本改写时加入成长主题与重复句式）。
