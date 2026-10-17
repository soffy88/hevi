# BRANDFILM 单元：把 code-brand-film（MIT，nutllwhy）内化为 Hevi 的 CPU「15 秒品牌片」线
上游参考：/data/soffy/refs/code-brand-film（只读）。worktree：/data/soffy/projects/hevi-brandfilm，分支 feat/brand-film，基于 7087c24a。

## 上游要点
- 画面是一页 HTML，由一条暂停的 GSAP 时间轴驱动，再交给 HyperFrames（heygen）逐帧渲染。
- 配乐是 Python/numpy 合成的原创曲，节拍对准画面切点。
- 三道质量闸门：
  - film_audit.py：静态检查代码；
  - layout_audit.mjs：用 puppeteer 逐帧检查摆位，包括越界、重叠、安全区；
  - frame_audit.py：检查渲染出的画面。
- 流程顺序：先写 shot-list.md 和 copy.md，再写代码；闸门全部 0 failed 才允许交付。

## 步骤
1. **调研**：写 BRANDFILM_EVAL.md，说明以下几点：
   - 上游流水线；
   - HyperFrames 能否在 CPU 上的 headless Chromium 跑；跑不了就改用 Hevi 现有的 Playwright 逐帧截图，参照 scene3d 的 window.__setTime(t) 做法；
   - 和 artmotion、amtpl、amrules、sfxbad 的重叠与差异；
   - 哪些部分可以 vendor，第三方许可证（Noto OFL、GSAP 等）怎么处理。
2. **vendor**：放到 hevi/layer4_legacy/brandfilm/，保留 LICENSE 和 THIRD_PARTY_NOTICES，并登记到 docs/third_party/provenance-ledger.yaml。上游自带的 examples/office-agent 要完整渲染通过，三道闸门都是 0 failed。
3. **接入 line=brandfilm**：
   - 输入：品牌名、卖点、可选 logo/产品图；
   - 流程：shot-list → copy → HTML/GSAP → 逐帧渲染 → 节拍对齐的合成配乐（切点误差 ≤1 帧）→ 闸门；
   - 支持 16:9 和 9:16 两种画幅，竖屏要重新排版，不能直接裁切；
   - 时长 15 秒，允许 ±0.1 秒。
4. **闸门复用**：把 layout_audit 的逐帧文字越界、重叠检测抽成 Hevi 的通用闸门函数，至少给 amtpl 模板调用一次，做出示例。amtpl 当前的失败项就是文字重叠和安全区只查画布。只提供函数和示例，不要改 amtpl 分支。
5. **E2E 样片**：
   - 横屏、竖屏各 1 条，都是 15 秒，品牌用虚构的「Hevi 视频工厂」；
   - 每条交付 MP4、封面、shot-list、copy、三道闸门报告、sha256、时长、LUFS、联系表；
   - 用 ffprobe 确认有音轨。
6. **测试**：
   - pytest 覆盖以下几点：
     - 配乐重拍落在切点上；
     - 闸门能抓出人为制造的越界、重叠、黑帧；
     - 删除任意一个产物，测试必须失败；
     - 同一 seed 渲两次结果可复现；
   - 3O lint 不新增失败。

## 规则
- 纯 CPU，不调用付费 API，不 push。
- 只改本 worktree；不删 worktree 外的任何文件；不清理磁盘。/data 剩余空间小于 5G 时写 DISK_FULL_NOTE.md 并停止。
- 长时间的 E2E 用 nohup setsid 后台跑，再轮询结果。
- 完成后在 BRANDFILM_DONE.md 最后一行写 DONE BRANDFILM-R1。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-brandfilm；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 BRANDFILM_DONE.md 最后一行写 DONE BRANDFILM-R1。

## 追加要求（2026-10-14 16:50）：能力契约
本线的能力必须按本 worktree 里的 CAPABILITY_CONTRACT.md 注册到 hevi/capabilities/registry.py，让各个产品线都能按名字调用，不要只做私有入口。如果本分支里还没有 registry.py，就按契约建一个最小实现（webkit 单元负责权威版本，最后合并时以它为准）。DONE 报告里要列出本线注册的全部能力名。
