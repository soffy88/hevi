# ARCHIFY_TASK — 解说视频图示来源：搜现成图 / Archify 生成

分支 feat/archify-visuals（worktree /data/soffy/projects/hevi-archify，基于 origin/closure/3o-v3-architecture-creative-baseline @ac09c747）。
上游已放到 third_party/archify（tt-a1i/archify v3.0.1，MIT，已去掉 .git）。

## 目标
Hevi 的解说视频（explainer：hevi/layer4_legacy/talkcraft 的 Remotion explainer，以及 zerolines 里的 explainer 类线路——先 grep 找到"镜头/分镜需要画面"的地方）在某个镜头需要图示时，按镜头自动选择：
- (a) **搜索现成图**：真实物体/场景/人物/产品 → 现有素材检索（仓库里已有的 Pexels/Pixabay/本地素材库检索，先找已有实现复用，不新增付费 API）。
- (b) **Archify 生成**：结构/解释性内容（架构、流程 workflow、时序 sequence、数据流、生命周期、学习路线 roadmap、时间线 timeline 等）→ LLM 写 Archify 的类型化 JSON IR → `node third_party/archify/bin/archify.mjs deliver <type> <json> <out.html> --json` 渲染 → headless 截成 PNG（静态）或 MP4（用 Archify 自带 Export/动效能力，或 Playwright/puppeteer 逐帧录制）→ 放进分镜镜头。
- 选择逻辑要可解释：每个镜头记录 `visual_source: search|archify`、原因、archify type、IR 文件路径。

## 必须做到
1. 封装成 Hevi 内部模块（建议 hevi/visuals/archify_source.py + 选择器 visual_router.py），有清晰接口；LLM 调用走 Hevi 现有的 LLM 网关/本地配置（不得调用付费云 API；若必须用 LLM，用仓库已有的免费/本地 provider；没有时允许用确定性规则从镜头文案生成 IR，并在 DONE 里如实说明）。
2. 先读 third_party/archify 的 README/AGENTS.md/docs，搞清每种 type 的 IR schema，IR 生成后用 archify 自带校验（deliver --json 的错误输出）校验，失败要重试/降级到 search，不得静默。
3. **9:16 竖版**：用 Archify 的布局参数/主题生成竖版画布或按竖版重新排版，**禁止把横图硬裁成竖条**；16:9 也要支持。
4. **文字不溢出**：截图后做自动检查（DOM 层面检测元素 scrollWidth>clientWidth 或超出视口，或图像层面检测文字贴边），溢出则缩字号/换行/换布局重渲；写进门禁。
5. **MIT 署名**：保留 third_party/archify/LICENSE、THIRD_PARTY_NOTICES，并在仓库的第三方台账（NOTICE / third_party/README.md 等现有位置）登记。
6. node 依赖：如需 npm install，用 ~/.nvm 的 node v26.4.0，走代理 127.0.0.1:7890 或 npmmirror；headless 浏览器复用仓库/机器上已有的 chromium（hyperframes/puppeteer 已在用），不要另下大包重复安装。
7. 测试：tests/test_archify_visuals.py —— 真实调用 archify 渲染至少 3 种 type（如 architecture、sequence、timeline），断言 PNG 尺寸、非空白、无溢出；路由器对"真实物体"镜头选 search、对"流程/架构"镜头选 archify。禁止 mock 渲染结果。
8. **E2E 样片**：做一条完整的解说样片（中文，约 30–60s，9:16），主题建议「一个网页请求是怎么到达服务器的」或「Hevi 视频生成流水线」，至少 2 个镜头用 Archify 生成（含 1 个动效 MP4 镜头更好）、至少 1 个镜头用搜索素材；有本地 TTS 配音（piper/现有本地 TTS）。输出到 output/archify_e2e/，写 record.json（每镜头来源、原因、文件、sha256）+ contact sheet。
9. CPU-only（GPU 坏了）；长任务 nohup setsid 后台跑并轮询；不触碰主 checkout /data/soffy/projects/hevi；不删任何数据；不调付费 API；不 push、不合并。
10. 3O lint（scripts/ci/run_3o_v3_lint.py）不得新增失败（基线 4 项）；pytest 相关测试通过。

## 交付
- 分阶段 git commit（只 add 自己的文件）。
- ARCHIFY_DONE.md：如实写做了什么、接口、门禁、样片路径和 ffprobe/sha256、已知限制。不得自评"独立验证通过"，不得写未实测的数据。
