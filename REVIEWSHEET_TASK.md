# REVIEWSHEET_TASK — 单元 K2：分镜审稿表 PNG + 帧标注→ShotSpec patch + kids_gate 后期 QC

- worktree：`/data/soffy/projects/hevi-reviewsheet`，分支 `feat/review-sheet`
- 基线：`feat/kids-gate` HEAD `46d7c050`，已合并 `feat/shot-spec` `8b2588b2`（提供 ShotSpec 校验器与 PATCH 路由）→ 当前起点 `ff7eec6d`
- 依据：`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` 第 3 节（3.3 schema、3.4 审稿表规格、3.5 标注映射表、3.6 QC 清单）与第 4 节「单元 K2」。先完整读这两节。
- 完成文件：`REVIEWSHEET_DONE.md`；完成标志（最后一行）：`DONE REVIEWSHEET-R1`

## manifest schema 依赖（重要）
K1（`feat/kids-manifest`，worktree `/data/soffy/projects/hevi-kidsmanifest`）在并行开发 `KidsConsistencyManifest`。本单元**不要等它**：先按 RENOISE_EVAL 3.3 的草案 schema 在本分支实现一个最小只读加载层（如 `hevi/kids/manifest_draft.py`），所有消费 manifest 的代码只通过一个适配点（如 `hevi/kids/manifest_adapter.py` 的 `load_manifest()` / 协议类）访问，便于日后换成 K1 的正式实现。不得修改 K1 的 worktree；可只读参考其已 commit 的代码。

## 目标
1. `review_sheet`（建议 `hevi/kids/review_sheet.py`，复用 `hevi/ingest/contact_sheet.py` 的 PIL 布局与中文字体）：从 manifest + ShotSpec 渲染网格 PNG，每格镜号/时长/台词/机位/景别/缩略图（缺关键帧用灰底占位）；页脚按 3.4 格式；9:16 与 16:9 各一；PDF 可选。仅供审稿预览，不作生成输入。
2. `annotation_revision`（建议 `hevi/kids/annotation_revision.py`）：标注（pin/arrow/freehand/rect/ellipse/text）+ `sourceTimeMs` → 确定性 `ShotSpecPatch{shot_index, from_revision, changes, advisory, source_refs}`，严格按 3.5 映射表；dry-run diff；未知映射只进 advisory；干净原图与标注图分离；≥2 个时间码锚点 → `requiresTemporalRangeClarification=true`，不生成区间 patch；patch 应用走既有 ShotSpec PATCH 语义与校验器。
3. `kids_gate` 扩展（`hevi/quality/kids_gate.py`）：在原 6 项外加 3.6 的连续性/服装道具/地点/画风调色/Transition Table/口语语言/转场类型检查，统一 `status/violations/warnings/timecodes/metrics` 报告 + 完整 checklist。
4. 新能力注册进 `hevi/capabilities/registry.py`。

## 可测验收标准
1. 审稿表：N 镜输入 → PNG 恰 N 格；每格镜号/时长（±0.05s）/台词/机位可见；同输入两次输出 SHA-256 相同；9:16 与 16:9 各一张；缺关键帧用占位不崩。
2. 标注修订：在 S3 上画 `pin + arrow` → patch 只改映射字段，其余字段字节不变；未知标注 → advisory 且 `changes` 为空；时间码落在镜外 → 拒绝；≥2 个时间码锚点 → 要求区间澄清，不自动出 patch。
3. kids_gate：对一条真实 CPU 渲染片（manga / handdraw / scene3d 任一本地产物，或在本 worktree 用本地引擎/ffmpeg 现渲一条）跑扩展门，原 6 项不误伤（原 PASS 仍 PASS）；对人工构造的连续性坏样本（错误服装/色温跳变等，用真实 ffmpeg 制作）红灯并给出时间码；报告含完整 checklist。
4. CPU-only + 无 mock：全部用真实 ffmpeg/PIL 本地产物验收，无远程调用，确定性可复现。
5. 端到端：一部试点片 `manifest → review_sheet → 标注 patch → 应用 → 重新渲染 → kids_gate` 全链路走通（本地引擎渲染，无付费 API），产物路径与哈希写进 DONE。
6. 新增单测真跑全过；既有 kids_gate / shot_spec 测试不回归；3O lint 失败数 ≤4。

## 硬规则（必须遵守，违反即视为未完成）

1. **方向与契约**：开工前完整阅读本 worktree 根目录的 `KIDS_ANIME_DIRECTION.md`（Hevi 幼儿动漫方向）和 `CAPABILITY_CONTRACT.md`（能力契约）并遵守。本单元新增的每项能力都必须注册进 `hevi/capabilities/registry.py`，可被所有产线通过 registry 调用（`get/resolve`），并有测试证明可从 registry 调起。
2. **只在本 worktree 内工作**：不得修改主 checkout `/data/soffy/projects/hevi` 或任何其它 worktree；临时文件一律放本 worktree 的 `.tmp/`（并确保 `.tmp/` 不被提交）。
3. **CPU-only**：不调用任何付费 API / 远程 provider，不联网下载大模型；测试无网络出站。
4. **绝不删除 worktree 外的任何东西**；绝不"清理磁盘"，不删 node_modules、缓存、模型、其它项目文件。`df /data` 剩余 <5G 时写 `DISK_FULL_NOTE.md` 并立即停止。
5. **内存紧张**（整机 30G、多任务并行）：渲染与重测试单进程跑（pytest 不开 -n，ffmpeg 单路）；长任务用 `nohup setsid ... &` 启动并轮询到完成，产物完成前不得结束会话。
6. **禁止 mock / 占位 / 硬编码通过**：测试必须真跑真实代码路径和真实 ffmpeg/PIL 产物。pytest 以 soffy 身份运行：
   `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest <tests> -q`
7. **3O lint**：`PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py`，失败数不得超过基线 4（基线 4 项：check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），不得新增失败项。lint 日志不要提交进仓库。
8. **许可**：Renoise 仓库无 LICENSE —— 只吸收方法论，不复制其原文或代码。BeefTV 为 MIT —— 借鉴的设计/代码须在仓库根 `NOTICE` 中署名，不得整包 vendor。
9. **git**：阶段性 commit，只 `git add` 自己创建/修改的文件（不要 `git add -A`）。不 push、不合并到其它分支、不改写历史。不要询问，直接执行到底。
10. **完成**：写 `REVIEWSHEET_DONE.md`，如实记录每条验收标准的实测结果（命令、通过/失败数、SHA-256、产物路径），未达成的如实写明；最后一行写完成标志，然后 commit。
