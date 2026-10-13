# SHOTSPEC_TASK — W1 ShotSpec 后端（分支 feat/shot-spec）

## 背景
GAP_PLAN §2 W1：没有统一的单镜规格。本单元新增 ShotSpec（模板/入场转场/特效/风格/音效/运镜/字幕样式/时长），提供 API，并让 assembler 渲染时读取 spec。
本 worktree `/data/soffy/projects/hevi-shotspec` 已建好：基于 `origin/feat/fx-registry`（2daa4e4d，T1 注册表 `hevi/fx/registry.py`），并已合入 `feat/xfade-pack`（T2，`hevi/assembly/xfade_transitions.py` + `build_xfade_chain` 支持逐接缝 list）和 `origin/feat/sfx-badclips`（0e98896e，`assets/audio/sfx/library/manifest.json`）。xfade-pack 仍有 whip 修复在途，之后本分支会 rebase；你不要去改 xfade_transitions.py 里的转场表达式。

## 范围（文件边界）
- 新增 `hevi/production/shot_spec.py`：pydantic 模型 `ShotSpec`，字段：
  - `template`（T1 FX 注册表里的模板 id）
  - `transition_in`（xfade-pack 注册表 id；第 1 镜忽略/允许 None；`cut` 表示硬切）
  - `effect`（`warm|cool|mono|vignette|sharpen` + 注册表里能映射成 ffmpeg 滤镜的 style 类条目，尽力而为）
  - `style`：若 `hevi/layer4_legacy/dirstyle` 存在，则校验为 dirstyle 风格 id；否则为自由字符串，代码里标注 `# TODO(dirstyle): validate once feat/director-styles merges`。**dirstyle 目前未合并，不要创建或改动 dirstyle 的任何文件。**
  - `sfx`: `list[{id, offset}]`（id 必须存在于 sfx manifest / 注册表 sfx 源；offset 为相对本镜起点的秒数，0 ≤ offset < duration）
  - `camera`、`subtitle_style`、`duration`（>0）
  - 所有可选字段允许 None；值全部用注册表/manifest 校验，未知值返回 422。
- API 路由（新增 router 或放进现有 tasks/production 路由，挑最小侵入的方式，挂到 app）：
  - `GET /tasks/{id}/shots/{i}/spec`
  - `PATCH /tasks/{id}/shots/{i}/spec`（部分更新）
  - `PUT /tasks/{id}/shots/spec`（批量，整组替换，逐条校验，任一非法整体 422）
  - spec 持久化到任务现有存储（看 tasks 现有 shot 数据怎么存，跟随它；不要新建数据库）。
- 渲染：assembler 读取 spec。
  - `hevi/assembly/assembler.py` **只能通过 xfade-pack 已提供的接口扩展**（`build_xfade_chain(transition=list[...])` 及上层透传）；新逻辑尽量放到新文件，例如 `hevi/production/shot_spec_render.py`（spec → 每接缝转场 list、每镜 ffmpeg 滤镜链、sfx 混音 adelay/amix）。
  - effect → ffmpeg 滤镜：warm（colorbalance/colortemperature 偏暖，R/B 比上升）、cool、mono（hue=s=0 或 format=gray，色度 ≈0）、vignette、sharpen（unsharp），以及注册表 style 能做的。
  - sfx 按（镜头起点 + offset）混音，镜头起点需扣除 xfade 重叠（offset_i 与 build_xfade_chain 一致）。
- 新增测试 `tests/test_shot_spec_api.py`（API 单测，TestClient）、`tests/test_shot_spec_render.py`（真实 ffmpeg 验收）；脚本 `scripts/shot_spec_demo.py`（生成验收样片）。

## 禁止改动
同 COMMON.md 列表：`hevi/video/quality_profile.py`、`hevi/studio/*`、`hevi/prompt/style_presets.py`、`hevi/keyframe/**/style_presets.py`、`hevi/layer4_legacy/review/*`、`hevi/layer4_legacy/enhance/*`、`hevi/layer4_legacy/dirstyle/*`、`hevi/production/capabilities.py`、`hevi/api/routers/explainer.py`、`hevi/explainer/*`。
例外：`hevi/assembly/assembler.py` 允许经 xfade-pack 接口做最小扩展（保持向后兼容，旧调用的 filter_complex 不变）。也不要改 `hevi/fx/*` 和 `hevi/assembly/xfade_transitions.py`（只读调用）。

## 步骤
1. 跑 lint 基线 `lint_before.txt`（注意本分支已有合并来的 lint_before.txt，直接覆盖）；读 fx/registry.py、xfade_transitions.py、assembler.py、sfx manifest、tasks 路由。commit。
2. shot_spec.py + 校验；API 路由 + `tests/test_shot_spec_api.py`（GET/PATCH/PUT 正常、未知 template/transition/effect/sfx id → 422、offset 越界 → 422、批量部分非法整体 422、404）。commit。
3. shot_spec_render + assembler 接入；回归：不带 spec 的旧渲染路径行为不变（复用 test_xfade_pack 的 golden）。commit。
4. E2E 样片 `output/shotspec_e2e/`：4 个镜头（每段 3s，1080x1920，30fps，lavfi 不同图案或仓库已有真实片段，彩色），其中 3 镜用 3 份不同 spec，例如：
   - 镜1 effect=warm，sfx=[whoosh@1.0]
   - 镜2 transition_in=某 builtin，effect=mono，sfx=[impact@0.5, ding@2.0]
   - 镜3 transition_in=某 custom，effect=cool 或 vignette，sfx=[pop@1.5]
   - 镜4 无 spec（默认）。
   同时出“无 spec 基线”同素材渲染。先 render 一次，再通过 API PATCH 改 1 镜 spec 后**重渲**，证明 spec 改动生效。写 `record.json`（命令、filter_complex、ffprobe、sha256、spec JSON）。长渲染用 nohup setsid 跑并轮询。commit（>20MB 不提交）。
5. 真实验收（写进 `tests/test_shot_spec_render.py`，真实 ffmpeg，不 mock）：
   - 音效位置：对成片音轨（样片底音用静音或极低电平，便于检测）用 silencedetect 或短时能量峰值，每个 sfx 起点 = 镜头起点（扣重叠）+ offset，误差 ±0.1s；
   - 特效：mono 镜中段帧 U/V 色度相对 128 的平均偏差 ≈0（如 <2）；warm 镜 R/B 均值比 相对基线同时刻帧上升；
   - 转场：每个接缝中点抽帧，与硬切基线同时刻比较确有过渡（SSIM < 0.98），且 spec 指定 `cut` 的接缝为硬切；不同接缝转场形态不同；
   - 成片时长 = Σ时长 − Σd（±1 帧）。
6. lint_after（失败数 ≤4，即只有基线的 4 项）；写 `SHOTSPEC_DONE.md`，commit。

## 通用规则（必须遵守）
- 你在独立 worktree 里工作（当前目录 `/data/soffy/projects/hevi-shotspec`），基础分支是 `feat/shot-spec`（已含 fx-registry + xfade-pack + sfx-badclips）。**绝对不要碰主 checkout `/data/soffy/projects/hevi`**（只允许只读引用其 .venv / node_modules，已为你建好软链）。也不要改其它 hevi-* worktree。
- CPU-only（GPU 已坏）；不调用任何付费 API；不重建容器；不删任何数据；不 push、不合并其它分支。
- 所有 python/pytest 命令都设 `PYTHONPATH=/data/soffy/projects/hevi-shotspec`（否则会导入主 checkout 的代码）。
- 开工先跑 `PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1` 记基线（基线允许 4 项失败），结束再跑 `lint_after.txt`，失败数不得多于 4。
- pytest 运行：`PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest <你的测试> -q`。PATH 已含 /home/soffy/.local/bin（ffmpeg/ffprobe 在那里）。
- `output/` 被 .gitignore 忽略，需要提交的小产物（record.json、抽帧图等）用 `git add -f`。
- 每完成一步就 `git add <只加自己的文件> && git commit -m "feat/shot-spec: step N ..."`（不要 `git add -A`；不要提交 >20MB 文件、node_modules、.venv 软链、日志、.cc_prompt.txt）。仓库有 LFS hook 报 git-lfs 缺失的警告，可忽略（commit 本身会成功，用 git log 确认）。
- 长任务（批量渲染/E2E）用 `nohup setsid <cmd> > <log> 2>&1 &` 独立启动，sleep 轮询直到产物生成，不得在产物完成前结束。
- 禁止 mock/占位/写死产物；验收数据必须来自真实 ffprobe/抽帧/测试输出。DONE 里不得写未实测的数据，不得自称"独立验证通过"。
- 不要询问，直接执行到底。最后写 `SHOTSPEC_DONE.md`（做了什么、文件清单、接口、测试命令与真实结果、产物路径+ffprobe+sha256、lint 前后、已知限制），commit，**最后一行写 `DONE SHOTSPEC-R1`**。
- 注意：`.venv` 是指向 /data/soffy/projects/hevi/.venv 的软链（git status 里会显示为未跟踪），**不要删除也不要提交**；若丢失用 `ln -s /data/soffy/projects/hevi/.venv .venv` 重建。
- **磁盘安全规则（硬性）**：绝对不要删除 worktree 目录之外的任何文件；绝对不要做任何"清理磁盘空间"的操作（不删缓存/镜像/卷/日志/他人目录）。开工和每次大渲染前 `df -h /data`：若可用 < 5G，写 `DISK_FULL_NOTE.md` 说明后停止，等主会话处理。
