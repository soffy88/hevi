# WEBKIT 单元：按层补齐「代码动画工具链」（用户 2026-10-14 16:38 提供的 20 个工具清单）
worktree：/data/soffy/projects/hevi-webkit，分支 feat/webkit-layers，基于 origin/closure/3o-v3-architecture-creative-baseline（ac09c747）。

## Hevi 已有的部分，不要重做
- Remotion：talkcraft
- GSAP：brandfilm 单元在做
- Three.js：scene3d 单元在做
- FFmpeg：全线
- 逐帧确定性截图：omrender / scene3d 的 window.__setTime(t)

## 步骤
1. **TOOLKIT_MAP.md**：把 20 个工具按 7 层列成表：agent 技能、动画、3D、素材、声音、导出、审片。每个工具写明以下几项：
   - Hevi 有没有、在哪个文件；
   - 能不能 CPU headless 逐帧渲染；
   - 许可证；
   - 结论：接入 / 已有 / 不需要。Howler 和 Mediabunny 是浏览器播放、编码用的，离线渲染多半用不上，要写清理由。
2. **共享渲染底座**：建 hevi/webrender/。用 Playwright Chromium（SwiftShader）打开一个 HTML，通过 seek(t) 精确跳到第 t 秒再截帧，并发截帧后交给 ffmpeg 编码。scene3d 和 brandfilm 以后可以改用它，本单元只提供底座和示例，不改那两个分支。
3. **接入以下 4 项**，每项至少 1 个示例 + 1 条 pytest：
   a. **dotLottie / lottie-web**：用 goToAndStop(帧) 确定性渲染，放到 B-roll 叠加层和图标动效里。素材只用 LottieFiles 上明确标为免费的；能下多少下多少，至少 10 个，登记到 ASSETS.md（附来源 URL）。
   b. **Satori + resvg**：用 JSX 生成标题卡、字幕卡的 SVG，再转 PNG，不需要浏览器、很快。要支持中文，字体用 Noto Sans SC；做 16:9 和 9:16 两种版式。
   c. **SVGO**：Archify、artmotion 的 SVG 进动画前先过一遍清理，并给出前后体积对比。
   d. **Motion Canvas**：评估它能不能 headless 导出。能的话，做一条 20–30 秒的图表讲解示例（柱状图生长 + 数字滚动 + 中文标注）；不能的话，在报告里写明原因，并改用 Anime.js 在 webrender 里做同样的示例。
4. **agent 技能**：读 Remotion Skills、GSAP Skills、Motion AI Kit 的规则文档，提炼出 Hevi 工人写动画代码时要遵守的规则卡，例如时间线必须暂停后再 seek、React 卸载时要清理、禁止依赖实时 rAF 等。写进 amrules 的规则卡格式，放在 docs/rules/web_animation.md；要原创改写，不要整段照抄。
5. **流程闸门**：把 brief → design → animate → build → sound → render → review → ship 落成 hevi/webrender/pipeline.py 里的阶段清单。每个阶段写明产物和检查项；review 阶段至少要接 黑帧检查、文字越界检查、ffprobe 音轨检查。缺任何一个阶段的产物，就不允许进入 ship。
6. **E2E**：用 Satori 标题卡 + 2 个 Lottie 叠加 + Motion Canvas（或 Anime.js）图表，拼一条 30 秒 9:16 样片。CosyVoice 生成旁白，音效从 sfxbad 库里取。交付 MP4、sha256、时长、LUFS、联系表。
7. **测试**：pytest 覆盖以下几点，跑完后 3O lint 不新增失败：
   - 同一 t 截两次结果一致；
   - Lottie 帧单调变化；
   - Satori 中文没有豆腐块；
   - 删除任意一个产物，测试必须失败。

## 规则
- 纯 CPU，不调用付费 API，不 push。
- 只改本 worktree；不删 worktree 外的任何文件；不清理磁盘。/data 剩余空间小于 5G 时写 DISK_FULL_NOTE.md 并停止。
- npm 包装在本 worktree 的 node_modules 里，不要提交进仓库。
- 长时间的 E2E 用 nohup setsid 后台跑，再轮询结果。
- 完成后在 WEBKIT_DONE.md 最后一行写 DONE WEBKIT-R1。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-webkit；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 WEBKIT_DONE.md 最后一行写 DONE WEBKIT-R1。

## 追加要求（2026-10-14 16:50）：能力契约
本线的能力必须按本 worktree 里的 CAPABILITY_CONTRACT.md 注册到 hevi/capabilities/registry.py，让各个产品线都能按名字调用，不要只做私有入口。如果本分支里还没有 registry.py，就按契约建一个最小实现（webkit 单元负责权威版本，最后合并时以它为准）。DONE 报告里要列出本线注册的全部能力名。
