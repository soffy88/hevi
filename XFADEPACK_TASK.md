# XFADEPACK_TASK — T2 逐接缝转场包（分支 feat/xfade-pack）

## 背景
`hevi/assembly/assembler.py::build_xfade_chain(durations, transition, xfade_d)` 目前整片只用一种 xfade 转场；`xfade_d` 已支持逐接缝列表（beat_align）。目标：每个接缝可单独选转场，并接入 ffmpeg 内置约 40 种 xfade 转场 + 6–10 个 `xfade=transition=custom:expr=...` 自定义转场。

## 范围（文件边界）
- 只有你可以改 `hevi/assembly/assembler.py`（最小改动，保持向后兼容）。
- 新增 `hevi/assembly/xfade_transitions.py`：转场注册表。每条：`id`、`name_zh`、`kind`（builtin|custom）、`ffmpeg`（builtin 名或 custom expr）、`tags`（如 soft/hard/energetic/glitch/zoom）、`default_duration`。builtin 名单请用 `ffmpeg -hide_banner -h filter=xfade` 实际列出的枚举核对，只注册本机 ffmpeg 真支持的（目标 ≥40）。custom ≥6：whip（横向甩镜模糊感）、glitch（块状错位）、flash（闪白）、zoom-punch（推进冲击）、ink/burn 等，用 xfade custom expr（变量 X,Y,W,H,P,A,B 等）实现。提供 `list_transitions()`、`get_transition(id)`、`resolve(id)->xfade 参数片段`。
- `build_xfade_chain` 的 `transition` 参数接受 `str`（原行为，所有接缝同一种）或 `list[str]`（长度 n-1，逐接缝）；列表元素可以是注册表 id，未知 id 抛 ValueError。调用 assembler 的上层（如 assemble 主函数）若有 `transition` 参数，同样透传 list。
- 不改 `hevi/studio/*`（NLE TRANSITIONS 以后由 W3/T1 读你的注册表，本轮不改）。不新建 `hevi/fx/`（那是 T1 的）。
- 新增测试 `tests/test_xfade_pack.py`；新增脚本 `scripts/xfade_pack_demo.py`（生成验收样片）。

## 步骤
1. lint 基线；读 assembler.py、beat_align.py 和现有 xfade 测试（grep tests 里 build_xfade_chain）。commit。
2. 注册表 + custom 表达式；单测：每个 builtin/custom 都能用 ffmpeg 真跑（两段 1s testsrc2/不同颜色 lavfi 片，xfade 0.5s）退出码 0、输出时长 1.5±1帧。commit。
3. build_xfade_chain 支持 list；回归：旧 str 调用生成的 filter_complex 字符串与改动前逐字一致（先在 step1 记录旧输出做 golden）。commit。
4. E2E 样片：`output/xfadepack_e2e/`：5 个镜头（不同颜色/图案的 lavfi 源或仓库已有真实片段，每段 3s，1080x1920，30fps）用 4 种不同转场（至少 1 个 custom），d=0.6s；另出同素材硬切基线。写 `record.json`（命令、filter_complex、ffprobe、sha256）。另出 `transitions_gallery.mp4` 或 contact sheet：每个注册转场一格中点帧（`contact_sheet.png`），亲自看图确认各转场肉眼可辨。commit（>20MB 不提交）。
5. 测试断言（tests/test_xfade_pack.py，真实 ffmpeg，不 mock）：
   - 成片时长 = Σ时长 − Σd（±1 帧，ffprobe）；
   - 在每个接缝中点（offset_i + d/2）抽帧，与硬切基线同时刻帧的 SSIM < 0.98（确有过渡）；4 个接缝两两之间中点帧的过渡形态不同（例如对 A/B 混合比例图做差异，或相互 SSIM 差异，自行设计但必须真实计算）；
   - str 旧参数回归一致；未知 id 抛错；注册表 builtin ≥40、custom ≥6。
6. lint_after；写 `XFADEPACK_DONE.md`，commit。
## 通用规则（必须遵守）
- 你在独立 worktree 里工作（当前目录），基线 `ac09c747`（origin/closure/3o-v3-architecture-creative-baseline）。**绝对不要碰主 checkout `/data/soffy/projects/hevi`**（只允许只读引用其 .venv / node_modules，已为你建好软链）。也不要改其它 hevi-* worktree。
- CPU-only（GPU 已坏）；不调用任何付费 API；不重建容器；不删任何数据；不 push、不合并。
- 禁止改动：`hevi/video/quality_profile.py`、`hevi/studio/*`、`hevi/prompt/style_presets.py`、`hevi/keyframe/**/style_presets.py`、`hevi/layer4_legacy/review/*`、`hevi/layer4_legacy/enhance/*`、`hevi/layer4_legacy/dirstyle/*`、`hevi/production/capabilities.py`、`hevi/api/routers/explainer.py`、`hevi/explainer/*`（这些有在途单元，只读）。
- 开工先跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1` 记基线（基线允许 4 项失败），结束再跑 `lint_after.txt`，失败数不得多于 4。
- pytest 运行：`JWT_SECRET=test-secret-local .venv/bin/python -m pytest <你的测试> -q`。PATH 已含 /home/soffy/.local/bin（ffmpeg/ffprobe 在那里）。
- `output/` 被 .gitignore 忽略，需要提交的小产物（record.json、contact_sheet、index.json 等）用 `git add -f`。
- 每完成一步就 `git add <只加自己的文件> && git commit -m "feat/xfade-pack: step N ..."`（不要 `git add -A`；不要提交 >20MB 文件、node_modules、.venv 软链、日志）。
- 长任务（批量渲染/E2E）用 `nohup setsid <cmd> > <log> 2>&1 &` 独立启动，sleep 轮询直到产物生成，不得在产物完成前结束。
- 禁止 mock/占位/写死产物；验收数据必须来自真实 ffprobe/抽帧/测试输出。DONE 里不得写未实测的数据，不得自称"独立验证通过"。
- 不要询问，直接执行到底。最后写 `XFADEPACK_DONE.md`（做了什么、文件清单、接口、测试命令与真实结果、产物路径+ffprobe+sha256、lint 前后、已知限制），commit，最后一行写 `DONE XFADEPACK-R1`。
- 注意：`.venv` 是指向 /data/soffy/projects/hevi/.venv 的软链（git status 里会显示为未跟踪），**不要删除也不要提交**；若丢失用 `ln -s /data/soffy/projects/hevi/.venv .venv` 重建。

- **磁盘安全规则（2026-10-13 硬性）**：绝对不要删除 worktree 目录之外的任何文件；绝对不要做任何"清理磁盘空间"的操作（不删缓存/镜像/卷/日志/他人目录）。磁盘满了就停下并在 DONE/日志里写明，等主会话处理。
