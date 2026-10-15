# FXREG_TASK — T1 统一模板注册表（分支 feat/fx-registry）

## 背景
talkcraft 有 109 张卡片元数据 `hevi-remotion-talkcraft/src/cards/tplMeta.ts`（7 类：字幕花字/素材呈现/强调标注/数据信息图/转场结构/人物互动/运镜；卡片在 `tplcards/`、`src/cards/gen/`、`gen-index.ts`）。Python 端只有 talkcraft 线和 `hevi/production/capabilities.py` 能用。ffmpeg xfade 内置转场未利用。需要跨生产线的统一模板目录 + API + 预览。

## 范围（文件边界）
- 新增 `hevi/fx/`：`registry.py`（FxTemplate pydantic/dataclass：`id`、`name_zh`、`category` ∈ {transition, character, style, overlay}、`source`（talkcraft|xfade|custom|sfx|…）、`source_ref`、`tags`、`duration_hint`、`preview_mp4`、`thumbnail`）、`sources/talkcraft.py`（解析 tplMeta.ts，**只读**，不改 talkcraft 任何文件；7 类映射到 4 个 category：转场结构→transition，人物互动→character，运镜/素材呈现→style 或 overlay 自行合理定义并写进文档）、`sources/xfade.py`（若 `hevi.assembly.xfade_transitions` 可导入就读它（另一单元 T2 在做，本分支没有），否则用 `ffmpeg -hide_banner -h filter=xfade` 解析枚举动态生成）、`sources/sfx.py`（若 `assets/audio/sfx/library/manifest.json` 存在就读，否则读现有 `assets/audio/sfx/*.wav`）。character 类目前只有人物互动卡片，预留 `char_transform` source（T3 以后填）。
- 新增路由 `hevi/api/routers/fx.py`：`GET /api/fx/templates?category=&source=&q=` 列表、`GET /api/fx/templates/{id}` 详情、`GET /api/fx/templates/{id}/preview`（返回 mp4/缩略图文件或 404）。在 `hevi/api/main.py` 只加 import + 一行 `include_router`，不改其它。
- 新增 `scripts/fx_preview.py`：给每个模板渲 2s 预览 mp4（540x960 或 720x1280 即可，30fps）+ 缩略图 jpg 到 `output/fx_previews/<id>.mp4|.jpg`，并写 `output/fx_previews/index.json`。talkcraft 卡片用 Remotion CLI 渲染（`hevi-remotion-talkcraft` 的现有渲染入口/composition，先读 package.json、scripts/、remotion.config.ts 和 Python 侧 `hevi/layer4_legacy/talkcraft/*` 现有调用方式；node_modules 已软链到主 checkout，**只读**）；xfade 转场用两段 lavfi 源做 2s 预览；sfx 用波形可视化（showwaves）+音频。并发 ≤2，整批用 nohup setsid 后台跑并轮询。渲染失败的卡片如实记 index.json 的 error，不得用静帧/占位顶替。
- `capabilities.py`、`explainer` 路由、talkcraft 源码全部只读。不改 assembler.py（T2 的）。
- 测试 `tests/test_fx_registry.py`。

## 验收
- 注册表条目 ≥80，每条 category 合法、id 唯一；talkcraft 109 张全部入表（数目与 tplMeta.ts 一致，测试里动态解析核对）。
- 预览：成功渲染的每条 ffprobe 合法、时长 2±0.1s、相邻帧差均值 >0.01（非静帧）；目标 ≥80 条成功，失败率如实统计。
- pytest 覆盖 API（FastAPI TestClient：列表、category 过滤、详情、404、preview 返回）。
- 亲自看几张缩略图拼成 `output/fx_previews/contact_sheet.png`（每类 ≥4 个）。

## 步骤
1. lint 基线；读 tplMeta.ts、talkcraft Python 调用、渲染入口。commit 调研笔记 `FXREG_NOTES.md`。
2. registry + sources + 单测。commit。
3. API 路由 + 测试。commit。
4. fx_preview.py，先试 3 条，再后台批量跑全部；轮询完成；生成 index.json、contact_sheet。commit（预览 mp4 总量若 >50MB 则只提交 index.json 和 contact sheet，mp4 留在磁盘写路径）。
5. 预览验收测试（读 index.json + ffprobe 真实校验）。lint_after；写 `FXREG_DONE.md`，commit。
## 通用规则（必须遵守）
- 你在独立 worktree 里工作（当前目录），基线 `ac09c747`（origin/closure/3o-v3-architecture-creative-baseline）。**绝对不要碰主 checkout `/data/soffy/projects/hevi`**（只允许只读引用其 .venv / node_modules，已为你建好软链）。也不要改其它 hevi-* worktree。
- CPU-only（GPU 已坏）；不调用任何付费 API；不重建容器；不删任何数据；不 push、不合并。
- 禁止改动：`hevi/video/quality_profile.py`、`hevi/studio/*`、`hevi/prompt/style_presets.py`、`hevi/keyframe/**/style_presets.py`、`hevi/layer4_legacy/review/*`、`hevi/layer4_legacy/enhance/*`、`hevi/layer4_legacy/dirstyle/*`、`hevi/production/capabilities.py`、`hevi/api/routers/explainer.py`、`hevi/explainer/*`（这些有在途单元，只读）。
- 开工先跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1` 记基线（基线允许 4 项失败），结束再跑 `lint_after.txt`，失败数不得多于 4。
- pytest 运行：`JWT_SECRET=test-secret-local .venv/bin/python -m pytest <你的测试> -q`。PATH 已含 /home/soffy/.local/bin（ffmpeg/ffprobe 在那里）。
- `output/` 被 .gitignore 忽略，需要提交的小产物（record.json、contact_sheet、index.json 等）用 `git add -f`。
- 每完成一步就 `git add <只加自己的文件> && git commit -m "feat/fx-registry: step N ..."`（不要 `git add -A`；不要提交 >20MB 文件、node_modules、.venv 软链、日志）。
- 长任务（批量渲染/E2E）用 `nohup setsid <cmd> > <log> 2>&1 &` 独立启动，sleep 轮询直到产物生成，不得在产物完成前结束。
- 禁止 mock/占位/写死产物；验收数据必须来自真实 ffprobe/抽帧/测试输出。DONE 里不得写未实测的数据，不得自称"独立验证通过"。
- 不要询问，直接执行到底。最后写 `FXREG_DONE.md`（做了什么、文件清单、接口、测试命令与真实结果、产物路径+ffprobe+sha256、lint 前后、已知限制），commit，最后一行写 `DONE FXREG-R1`。
- 注意：`.venv` 是指向 /data/soffy/projects/hevi/.venv 的软链（git status 里会显示为未跟踪），**不要删除也不要提交**；若丢失用 `ln -s /data/soffy/projects/hevi/.venv .venv` 重建。

- **磁盘安全规则（2026-10-13 硬性）**：绝对不要删除 worktree 目录之外的任何文件；绝对不要做任何"清理磁盘空间"的操作（不删缓存/镜像/卷/日志/他人目录）。磁盘满了就停下并在 DONE/日志里写明，等主会话处理。
