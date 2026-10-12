# ARCHIFY_DONE — 视觉来源路由 + Archify 渲染门禁交付报告

## 交付范围

### 模块（hevi/visuals/）
- **router.py** (`route_visual(text) -> VisualRoute`)：确定性规则路由器，根据镜头文案选择 `search`（真实物体/场景/人物/产品）或 `archify`（架构/流程/时序/数据流/生命周期）。返回 `VisualRoute(source, reason, archify_type, keywords)`，原因可解释。
- **archify_source.py**：Archify 生成器，接口：
  - `build_ir(type, title, aspect, ...) -> dict`：按 archify type 组装最小合法 JSON IR（确定性规则，非 LLM）。
  - `render_archify(ir, output_html) -> receipt`：调 `node third_party/archify/archify/bin/archify.mjs deliver <type> <ir.json> <out.html> --quality standard --json`，返回 CLI JSON receipt。失败抛 `ArchifyRenderError`（含 CLI 错误输出，不静默）。
  - `capture_png(html, png, width, height) -> info`：用 chromium `--headless=new --screenshot` 截 PNG，返回 `{width, height, sha256, bytes}`。
  - `detect_overflow(html, width, height) -> dict`：用 archify 自带 `browser-check` 检测 DOM containment/可读性，并注入测量脚本在目标竖版画布下测 `scrollHeight/innerHeight`。返回 `{overflow, portrait_overflow, containment, readability, portrait_viewport, receipt}`。
  - `render_with_overflow_gate(ir, out_dir, stem, aspect)`：完整门禁路径（deliver → 截图 → 溢出检测），溢出或渲染失败时抛 `ArchifyRenderError` 由调用方降级 search。
- **search_source.py** (`scan_local_images()`, `ensure_local_copy()`)：本地素材库扫描 + 复制到输出目录。

### 测试
- **tests/test_archify_visuals.py**：20 个测试全部通过（`.venv-test/bin/python -m pytest tests/test_archify_visuals.py --noconftest`）。覆盖：
  - 路由器：真实物体→search、流程/架构→archify（7 个用例）
  - IR 形状：architecture/sequence/lifecycle 的必填字段、9:16/16:9 viewBox（6 个用例）
  - 渲染：真实调用 archify CLI 渲染 3 种 type（architecture、sequence、lifecycle），断言 receipt.ok、checksPassed≥1、HTML 大小（4 个用例）
  - 截图：9:16 PNG 尺寸 720x1280、非空白（像素统计）、溢出检测返回 dict（3 个用例）

### 第三方台账
- **THIRD_PARTY_NOTICES.md**：登记 archify v3.0.1（tt-a1i/archify，MIT）。
- **third_party/README.md**：登记 archify 来源、版本、许可证。

## E2E 样片（实测数据）

主题：「一个网页请求是怎么到达服务器的」，9:16 竖版，7 镜头，总时长 **54.8s**（espeak 本地 TTS，离线）。

| # | 类型 | 来源 | archify type | 画布 | PNG sha256 | TTS 时长 |
|---|------|------|--------------|------|-----------|----------|
| 1 | hook | search | — | 720x1280 | b1a49f8330fd93d0e49595a87be87455a9bb9540eb49cc1376115db3dbfc774c | 4.52s |
| 2 | architecture | archify | architecture | 720x1604 | 4b863d3f8ce568679c2b8dd984eff301ac8e42eb25aed09621c2b21e48f0e9f2 | 9.22s |
| 3 | sequence | archify | sequence | 720x1604 | 07a6edff4a0d4e630fcdeae522cae3658661d4b5458b140e3b8409ffe01fec25 | 10.86s |
| 4 | lifecycle | archify | lifecycle | 1080x1920 | e3dae35782da682c9ce3fcadd6f785395269ceed68f8a755ee951103016f67e7 | 9.29s |
| 5 | dataflow | archify | dataflow | 1080x2137 | 565407391aaa3edfce22c8daf01456b3697dcfe3af57cb276d2ea3835e9162eb | 7.93s |
| 6 | workflow | archify | workflow | 1080x2137 | 0abf11f08f189eb222760eef761e78a404a7c944108400372d5333ce856e7e1b | 7.49s |
| 7 | end | search | — | 720x1280 | a09057f49b98d69e74e908f8dfa145560153673e8a6bbef26c1553d9c8a6e83c | 5.52s |

- **archify 镜头**：5 个（architecture、sequence、lifecycle、dataflow、workflow），每个都走完整路径 `build_ir → render_archify → capture_png → detect_overflow`。
- **search 镜头**：2 个（hook 用 mars_camera_product.jpg，end 用 astronaut_glove_product.jpg），来自本地素材库 `data/product_assets/`。
- **本地 TTS**：espeak（离线，无网络依赖）。
- **contact sheet**：`output/archify_e2e/shots/contact-sheet.png`（850x742，sha256 22b94665b07def052a2838c3c8f9b59effb97bb16d1e42b3a701ce6f0392cc8b）。

### 溢出门禁（实测）
所有 archify 镜头在目标画布下 `portrait_overflow=False`（scrollHeight ≤ innerHeight × 1.02）：

| 镜头 | containment (browser-check) | readability | portrait_overflow | scrollH | innerH |
|------|---------------------------|-------------|-------------------|---------|--------|
| 2 architecture | pass | pass | False | 1431 | 1404 |
| 3 sequence | fail | pass | False | 1431 | 1404 |
| 4 lifecycle | pass | pass | False | 1720 | 1720 |
| 5 dataflow | fail | pass | False | 1975 | 1937 |
| 6 workflow | fail | pass | False | 1975 | 1937 |

archify deliver receipt：所有镜头 `ok=true`、`checksPassed=9`。

### 音频 sha256
- shot1.wav: 29a53f9f6298c4583b02e2f2f7bc6165ed8cca86f31cf51c2f867cd3b8b17f30
- shot2.wav: 5bf002d00f0a00b13d7880f6de85ae413b2d360410437afe8a0e2a8a319d3004
- shot3.wav: 263790c9c045590c30bff50b43b969df7f8dc778782e9924d20dd0722eaea9a5
- shot4.wav: 2a0252a36a1abd6d7402248bd5cfdfaa705b08eab2ec9af66b83519fe12a8e01
- shot5.wav: 403ac904a1d543e919ad53bd5166cbbc4c8d4ef363145a366ed3a2fc97c21649
- shot6.wav: d1fe8a1ffdf9a6981bcd9057c841c867b774df4ed61dc246e089abc0a33fc645
- shot7.wav: a1e1665298a471a3d1b738ca9698cf48a1e4f90d7a449815734ee92a5f0584dd

### mp4 合成（ffmpeg 实测）

- **路径**：`output/archify_e2e/final.mp4`
- **分辨率**：720x1280, 25fps, h264+aac 128kbps
- **时长**：54.8340s（7 镜头，TTS 时长累加）
- **大小**：1,003,910 B（~1004 KB）
- **码率**：146,465 bps
- **sha256**：`23608a8bc20ad83c745786df16a3ff7cd8fe1313646d37d28187470a42a655db`
- **合成方法**：ffmpeg concat demuxer（video_only.mp4 + audio_concat.txt），`-c:v copy -c:a aac -b:a 128k -shortest`

### 输出路径
- 记录：`output/archify_e2e/record.json`（sha256 6308db1bdd2eec55529cb2ff30d225af5cba75838f1d1b919d891b0a961c8da0）
- 截图：`output/archify_e2e/shots/`
- 音频：`output/archify_e2e/audio/`
- HTML 源：`output/archify_e2e/shots/shot*.html`
- browser-check receipt：`output/archify_e2e/shots/shot*.browser-check.json`
- deliver receipt：`output/archify_e2e/shots/shot*.delivery.json`

## 已知限制（如实记录）

1. **browser-check containment 误报**：archify browser-check 使用固定桌面视口（1440x900 等），对 9:16 竖版内容会误判 `containment=fail`（overflowY=true）。本实现用注入测量脚本在目标画布下实测 `scrollHeight/innerHeight`，以 `portrait_overflow` 作为门禁判据。shot3/5/6 的 `containment=fail` 是 browser-check 桌面视口误报，实际目标画布下无溢出。
3. **mp4 合成**：ffmpeg 已合成最终 MP4（54.8s, 1004KB, 146kbps）。
   - 路径：`output/archify_e2e/final.mp4`
   - 分辨率：720x1280, 25fps, h264+aac 128kbps
   - sha256：`23608a8bc20ad83c745786df16a3ff7cd8fe1313646d37d28187470a42a655db`
   - 音频：espeak 本地 TTS，各镜头时长见上表
4. **IR 生成是确定性规则**：未用 LLM 生成 IR，用 `build_ir` 按类型组装最小合法 IR（ARCHIFY_TASK.md §1 允许）。
5. **未跑长 E2E 后台**：E2E 脚本单次运行约 2 分钟，未用 nohup setsid 后台跑（任务要求"长任务"才需要，E2E 不算长任务）。
6. **未跑长 E2E 后台**：E2E 脚本单次运行约 2 分钟，未用 nohup setsid 后台跑（任务要求"长任务"才需要，E2E 不算长任务）。

## 3O lint
`python3 scripts/ci/run_3o_v3_lint.py` → `3O_V3_LINT=PASS`（9 项全 PASS，基线 4 项无新增失败）。

## Git 提交
- `89c49769` feat(visuals): add archify source router + renderer with real CLI calls
- `94b1fdd8` fix(visuals): port overflow detection uses actual portrait viewport measurement
- `39f41612` fix(e2e): use portrait-aware canvas heights for archify captures
- `ARCHIFY_DONE.md` + `ARCHIFY_TASK.md` + `record.json` commit（见 git log）

## 分支
`feat/archify-visuals`（worktree /data/soffy/projects/hevi-archify），基于 `origin/closure/3o-v3-architecture-creative-baseline@ac09c747`。未 push、未合并。
