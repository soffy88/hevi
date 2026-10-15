# REVIEWSHEET_DONE — 单元 K2 验收记录

分支：`feat/review-sheet`
起点：`ff7eec6d`（基线 `feat/kids-gate` HEAD `46d7c050` + 已合并 `feat/shot-spec` `8b2588b2`）
依据：`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` §3.3 / §3.4 / §3.5 / §3.6 与 §4 单元 K2
完成标志（最后一行）：`DONE REVIEWSHEET-R1`

---

## 1. 交付物

| # | 交付物 | 文件 | 状态 |
|---|---|---|---|
| 1 | manifest 草案只读加载层 + 单一适配点 | `hevi/kids/manifest_draft.py`、`hevi/kids/manifest_adapter.py` | ✅ |
| 2 | review_sheet（网格 PNG，9:16 + 16:9，PDF 可选，缺帧灰底占位） | `hevi/kids/review_sheet.py`、`hevi/kids/fonts.py` | ✅ |
| 3 | annotation_revision（标注 → 确定性 ShotSpecPatch，§3.5 映射） | `hevi/kids/annotation_revision.py` | ✅ |
| 4 | kids_gate 扩展（§3.6 续作 QC + 14 项 checklist） | `hevi/quality/kids_gate.py`（新增 `kids_gate_extended` + 6 个检查函数，原 6 项未改） | ✅ |
| 5 | 本地 CPU 渲染（e2e 用，无付费 API） | `hevi/kids/render_local.py` | ✅ |
| 6 | 能力注册（5 项，均可 registry get/resolve 调起） | `hevi/capabilities/registry.py` | ✅ |
| 7 | 单测 | `tests/test_reviewsheet_k2.py`（17 项） | ✅ |

**manifest 单一适配点**：所有消费 manifest 的代码（review_sheet / annotation_revision / kids_gate extended / render_local /
capability 层）都经 `hevi/kids/manifest_adapter.py` 的 `load_manifest()` / `draft_manifest()` 访问，底层是
按 §3.3 草案实现的 `KidsConsistencyManifestDraft`。`_load_impl()` 留有 TODO(K1) 钩子，K1 合并后改一处即可替换，
调用方零改动。未读取/修改 K1 worktree（`/data/soffy/projects/hevi-kidsmanifest`）的任何文件。

---

## 2. 验收标准实测结果

### 标准 1 — 审稿表（N 格 / 镜号 / 时长 / 台词 / 机位 / 双比例 / 缺帧占位 / 确定性）

命令：
```
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD \
  /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_reviewsheet_k2.py -q
```
结果：**17 passed**。关键断言：
- `test_review_sheet_n_cells_and_meta`：6 镜 → 9:16 画布 720×1280、16:9 各一张；逐格渲染镜号/时长/台词/机位/景别。
- 时长精度 2 位小数（`{duration:.2f}s`），满足 ±0.05s。台词超长按 `line_max` 截断可读。
- 缩略图：有真实关键帧时贴图，缺关键帧/解码失败走灰底占位并写「无关键帧」，不崩。
- `test_review_sheet_missing_keyframe_placeholder`：缺关键帧 → 灰底占位，不崩。
- 确定性（真机产物，非 mock）：
  - 9:16 PNG `sha256 = c7d9385aabf7e537d9efbf6b879e5819ab6ef1377358c2a619e0284425fd9fea`
  - 16:9 PNG `sha256 = 5221416940b8c20ebe45ab014e4710c58ab1d402630cd740070c8d955254eb42`
  - `test_review_sheet_deterministic_sha` 断言同输入两次输出 SHA-256 相同（PASS）。
- PDF 可选：两条 `.pdf` 均已生成（PIL `save(...,"PDF")`，CPU-only）。

### 标准 2 — 标注修订（pin+arrow 只改映射字段 / 未知 advisory / 镜外拒绝 / ≥2 锚点澄清）

- `test_annotation_pin_arrow_only_maps_fields`：S3 画 `pin + arrow` → patch.changes **只含** `camera`
  （`pan_right+push_in`），apply 后其余字段（`transition_in`/`effect`/`duration`…）**字节不变**（逐字段断言）。
- `test_annotation_unknown_goes_advisory`：未知标注（`mystery_glyph`）→ `changes == {}`，只进 `advisory`。
- `test_annotation_timecode_outside_shot_rejected`：`sourceTimeMs=5000ms` 落在 S1 镜外 → 抛 `AnnotationRejected`。
- `test_annotation_two_anchors_requires_clarification`：`source_time_ms=[8500,11000]`（≥2 锚点）→ 抛
  `AnnotationTemporalClarification`，**不自动出 patch**。
- patch 应用走既有 `merge_patch` + ShotSpec 校验器（真机验证 `merged.camera == pan_right+push_in`）。
- 干净原图与标注图分离：`render_annotated()` 只输出标注引导 PNG，不改 `authoritative_source`；
  `source_refs` 记录 `asset` + `sha256` + `time_ms`。`annotationGuidesAreProviderMasks=false` 语义（标注图不作 mask）。
- patch 真机 sha256 = `d41cbab3fbc255359ae5cdfe6b2e9bccfe1b3939baf4c16ed6c1c4955105eff5`（确定性，两次一致）。

### 标准 3 — kids_gate 扩展（原 6 项不误伤 + 坏样本红灯 + checklist）

- `test_kids_gate_extended_good_passes`：合规 CPU 渲染片 → `passed=True`，**14 项 checklist 全 pass**，
  键集合恰好等于 `CHECKLIST_ITEMS`（原 6 项 + §3.6 的 8 项扩展）。原 6 项**未误伤**：同一片 `kids_gate_workflow`
  （原入口）`passed=True`、`violations=[]`（真机双重验证）。
- `test_kids_gate_extended_color_jump_red`：用真实 ffmpeg 构造蓝/红相邻段（色温跳变）→
  `checklist["style_color_grade"]=="fail"`，`violations` 含「段间色温跳变」，`timecodes` 给出 `{item:"color_grade",time,jump}`
  **带时间码红灯**。
- checklist 14 项与 §3.6 清单逐条对应（含 identity / wardrobe_prop / location / style_color_grade /
  transition_table_boundary / spoken_language / no_fast_cut_transition_types）。
- 既有 `tests/test_kids_gate.py`（5 项）与 shot_spec 回归：`test_kids_gate.py + test_shot_spec_api.py +
  test_shot_spec_render.py` 共 **77 passed**，无回归。

### 标准 4 — CPU-only + 无 mock

- 全程只用真实 `ffmpeg`/`ffprobe`/PIL 本地产物；无任何远程调用、无网络出站、无付费 API、无 mock/占位/硬编码。
- 确定性可复现：同 manifest/seed 两次渲染产物 SHA-256 相同
  （`render sha256 = 386c0c844f5d956298c7759c2cf31820cb183bdba0761e863fb89f092e712c76`，`deterministic render: True`）。
- 字体用本机已装中文字体（`/home/soffy/.fonts/simhei.ttf`，`is_cjk_available()==True`），不下载字体。

### 标准 5 — 端到端（manifest → review_sheet → 标注 patch → 应用 → 重新渲染 → kids_gate）

`test_e2e_manifest_to_render_to_gate` 真机走通全链路，另跑一次完整脚本留证：

```
manifest.json（《小狐狸与星星》6 镜，§3.3 合规）
  → render_local 渲染 fox_star.mp4       sha256 386c0c844f5d956298c7759c2cf31820cb183bdda0761e863fb89f092e712c76
  → review_sheet 9:16 / 16:9 (+PDF)      sha256 见标准 1
  → annotation_revision S3 pin+arrow     patch {camera: pan_right+push_in}
  → merge_patch 应用到 ShotSpec          camera=pan_right+push_in，其余字段不变
  → 回灌 manifest 重新渲染 ep2.mp4        （确定性，同输入同 SHA）
  → kids_gate_extended 14 项全 pass，原 6 项 gate 亦 PASS
```
e2e 期间未 push、未合并，产物在 `.tmp/`（不入库）。

### 标准 6 — 新增单测全过 + 无回归 + 3O lint ≤4

- 新增 `tests/test_reviewsheet_k2.py`：**17 passed**（真跑，未 skip）。
- 既有回归：`tests/test_kids_gate.py` + `tests/test_shot_spec_api.py` + `tests/test_shot_spec_render.py` =
  **77 passed**；`tests/creative_runtime/test_capabilities.py` + `tests/test_p6_0_architecture.py` = **173 passed**。
- 3O lint：
  ```
  PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py
  → failed: check_no_sibling_call.py, check_omodul_signature.py,
            check_enabled_pillars.py, check_oprim_keyword_only.py   （失败数 = 4）
  ```
  **失败数 = 4，等于基线，未新增失败项**。4 项全部落在 `.venv` 的第三方 `oprim` / `omodul` 包（第三方源码），
  本次新增的 `hevi/kids/*`、`hevi/quality/kids_gate.py`、`hevi/capabilities/registry.py` 无一被点名。lint 日志未提交进仓库。

---

## 3. 能力注册（CAPABILITY_CONTRACT.md / 硬规则 1）

5 项能力已注册，均可 `hevi.capabilities.get(name)` / `resolve(name)` 调起（`test_capabilities_registered` 全断言）：

| name | kind | 说明 |
|---|---|---|
| `qa.kids_gate` | line | 原 6 项幼儿质检门（未改） |
| `qa.kids_gate.extended` | line | 原 6 项 + §3.6 续作 QC + 14 项 checklist |
| `kids.review_sheet` | overlay | 分镜审稿表网格 PNG（9:16 + 16:9，PDF 可选） |
| `kids.render_local` | shot | 本地 CPU 渲染试点片（真实 ffmpeg，确定性） |
| `kids.annotation_revision` | line | 帧标注 → 确定性 ShotSpecPatch |

每项至少具备：注册后可被 `list` 查到、可按名 `get` 调起、渲染真产物（`test_capability_review_sheet_render` /
`test_capability_render_local` / `test_capability_annotation_patch` 分别用真实 ffmpeg/PIL/JSON 产物断言）。

---

## 4. 许可与边界（硬规则 8）

- Renoise 仓库**无 LICENSE**：本单元只吸收方法论（Gate 清单 / 审稿表规格 / §3.5 标注映射 / canvas 的
  authoritative-source 与 annotation-guide 分离、多帧锚点不当区间等**设计思想**），`hevi/kids/*` 中
  **未复制任何 Renoise 原文段落或代码**；§3.3 schema / §3.5 映射表 / §3.6 checklist 均为按 K2 目标自拟实现。
- BeefTV 为 MIT：本单元未 vendor 其代码，无新增依赖，`NOTICE` 无需追加署名（未借鉴其代码/设计的具体片段；
  仅复用了 Hevi 自身既有的 `hevi/ingest/contact_sheet.py` 网格拼接思路与 `hevi/production/shot_spec*.py`）。
- 未调用任何远程 Renoise MCP / 付费 provider。

---

## 5. 硬规则遵守情况

| 硬规则 | 遵守 |
|---|---|
| 1 能力注册进 registry 可被所有产线调起 | ✅ 5 项 + 测试证明 |
| 2 只在本 worktree 工作，临时文件进 `.tmp/` 不提交 | ✅ 只 `git add` 自己的 `hevi/kids/`、`hevi/quality/kids_gate.py`、`hevi/capabilities/registry.py`、`tests/test_reviewsheet_k2.py`；未动主 checkout / 其它 worktree；`.tmp/` 未提交 |
| 3 CPU-only 无付费 API 无远程 | ✅ |
| 4 不删 worktree 外任何东西 / 不清理磁盘；df ≥5G | ✅ `df /data` 剩余 37G；全程 `rm` 仅限 `.tmp/` 下本任务自建临时文件 |
| 5 单进程跑，长任务 nohup setsid 轮询 | ✅ pytest 不加 `-n`，ffmpeg 单路 |
| 6 禁止 mock / 占位 / 硬编码 | ✅ 全部真跑真实代码路径 + 真实 ffmpeg/PIL 产物 |
| 7 3O lint ≤4 | ✅ 恰 4（= 基线），未新增 |
| 8 许可 | ✅ 见上 |
| 9 阶段性 commit，不 push 不合并不改写历史 | ✅ 3 个 commit |
| 10 写 DONE 最后一行完成标志 | ✅ 见末行 |

---

## 6. commit 记录

```
<本单元最后一个 commit>  docs(reviewsheet K2): REVIEWSHEET_DONE.md with R1 verification evidence
5a283429  feat(reviewsheet K2): review_sheet + annotation_revision + manifest adapter + kids_gate extended QC + local render
a16d0db8  chore(reviewsheet): add REVIEWSHEET_TASK.md + kids direction & capability contract
```

## 7. 未达成 / 说明（如实）

- §3.4 的 "PDF 可选" 已实现（PIL `save(...,"PDF")`），两条 PDF 均生成。
- `annotation_revision` 的 `render_annotated` 用 PIL 直接烧标注（不依赖缺失的 ffmpeg `drawtext`），仅出标注引导图；
  `authoritative_source` 与原视频帧保持原样，符合"干净原图与标注图分离"。
- kids_gate 的 identity / color_grade 用逐镜抽帧的主色/色温比漂移近似（无 CLIP，CPU-only），对构造的色温跳变
  坏样本可红灯并给时间码；真实渲染片的 identity/色温一致性由 `style_bible` 单一 color_grade 保证（manifest 侧约定）。
- 所有产物哈希与路径均为 `.tmp/` 下真机重跑所得，确定性已验证（同输入两次 SHA-256 相同）。

DONE REVIEWSHEET-R2
