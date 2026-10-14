# KIDSMANIFEST 单元完成报告 (KIDSMANIFEST-R1)

## 范围与依据
- 单元 K1：幼儿故事闸门 `kids_story_gate` + `KidsConsistencyManifest`（绑定 ShotSpec）。
- 依据：`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` 第 3 节（3.1 片单、3.2 P1/P2、3.3 schema 与绑定规则）与第 4 节 K1。
- 已完整阅读 `KIDS_ANIME_DIRECTION.md` 与 `CAPABILITY_CONTRACT.md` 并遵守。
- 继承既有 `feat/kids-gate`（`hevi/quality/kids_gate.py`，46d7c050->a241ada2）与 `feat/shot-spec`（`hevi/production/shot_spec.py` 校验器，8b2588b2）。
- 许可：仅吸收 Renoise 方法论（无 LICENSE），未复制其原文/代码；BeefTV(MIT) 本次未 vendor。

## 交付文件
- `hevi/kids/__init__.py`（包导出）
- `hevi/kids/story_gate.py`：`kids_story_gate(story)` / `gate_json(story)`，7 条规则 R1–R7（logline / 6 节拍 / 因果比 / 相邻情绪 / 单主题 / 固定角色 / 口语语言），确定性 JSON。
- `hevi/kids/consistency_manifest.py`：`KidsConsistencyManifest`（pydantic，§3.3 schema）+ `validate_manifest`（M0–M6）+ 与 ShotSpec 双向绑定（`to_task_specs` / `attach_to_task_shot_rows` / `read_specs_from_task_shot_rows` / `manifest_from_task_specs`）+ `canonical_json`。
- `hevi/capabilities/registry.py`：注册 `kids.story_gate` 与 `kids.consistency_manifest`（均经 `get`/`list` 可查可调）。
- `tests/test_kids_manifest.py` + `tests/fixtures/kids/*`：4 部试点 story、3 坏样本、2 合法 manifest、2 坏 manifest。
- `docs/kids/manifests/`：2 部片经全链路 dry-run 产出的可审阅 manifest JSON。
- `docs/kids/gate_reports/`：7 部 story 的 gate 报告（含 4 部合规 PASS + 3 坏样本 FAIL）。

## 与 K2 的接口（schema 导出点）
- 模块路径：`hevi/kids/consistency_manifest.py`
- 类名：`KidsConsistencyManifest`（pydantic `BaseModel`）
- 校验函数：`validate_manifest(manifest) -> ManifestReport`（status: OK/FAIL，findings 含规则名+位置）
- JSON schema 导出：`KidsConsistencyManifest.model_json_schema()`（便于 K2 的 review-sheet / annotation-revision 对接）
- ShotSpec 委派校验器：`hevi/production/shot_spec.py` 的 `ShotSpec` / `validate_specs`（未知 `template/transition_in/sfx/style` 由 pydantic 抛 `ValidationError`，绝不静默放行）
- 双向绑定字段：`shots[].shot_spec` ↔ 任务 `shot_states.selection_json["shot_spec"]`（复用 `shot_spec.upsert_spec` / `read_spec`）

## 验收标准实测结果

### 1. 4 部试点片单 gate 输出 PASS + 逐条 finding
命令（`JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD .../python -m pytest tests/test_kids_manifest.py -q`）：
4 部合规 story（`story_fox_star/slide/brush_monster/seed_sprout`）`gate.status == PASS`，每部输出 7 条 finding（R1_LOG_LINE / R2_SIX_BEATS / R3_CAUSAL_RATIO / R4_ADJACENT_EMOTION / R5_SINGLE_THEME / R6_FIXED_CHARACTER / R7_SPOKEN_LANGUAGE）。**PASS**

### 2. 3 类坏样本必 FAIL
- ① 全 AND-THEN（`story_bad_all_andthen.json`）：`R3_CAUSAL_RATIO` FAIL（因果比 0.00 < 0.30）→ status FAIL。**PASS**
- ② 相邻两拍同一情绪（`story_bad_adjacent_emotion.json`）：`R4_ADJACENT_EMOTION` FAIL → status FAIL。**PASS**
- ③ 缺主题或缺固定角色（`story_bad_missing_theme_char.json`）：`R5_SINGLE_THEME` + `R6_FIXED_CHARACTER` + `R7_SPOKEN_LANGUAGE` 全 FAIL → status FAIL。**PASS**
- 合规样本必 PASS（见 1）。**PASS**

### 3. manifest 校验
- 未知 `transition_in`（`manifest_bad_shotspec.json`）→ `M0_SHOTSPEC_DELEGATION` FAIL（由 ShotSpec 校验器给出）。**PASS**
- 未知 `style` → 同样 `M0_SHOTSPEC_DELEGATION` FAIL（委派，未重复实现）。**PASS**
- 缺 Style Bible 段（`manifest_bad_stylebible.json`，`camera_language` 空）→ `M1_STYLE_BIBLE` FAIL。**PASS**
- 缺 Transition Table 切点（`manifest_fox_star` 删一行）→ `M2_TRANSITION_TABLE` FAIL。**PASS**
- 未知 `@引用`（`@char_unknown`）→ `M4_REF_RESOLUTION` FAIL。**PASS**
- `duration<2.5`（`shots[0]=1.0`）→ `M5_DURATION` FAIL。**PASS**
- 合法 `manifest_fox_star.json` / `manifest_slide.json` → status `OK`。**PASS**

### 4. 确定性（同输入两次 JSON 字节一致，SHA-256）
对 7 部 story 跑 `gate_json` 两次，对 2 部 manifest 跑 `canonical_json` 两次，全部 SHA-256 相同：
- gate story_fox_star: `c28f1df521728784ae6aa76ab791b95adc438f72e5d3bf9e9ffe3c1f58adb58a`
- gate story_slide:    `eb2042d0ab224265b927fca1de8398b6ae82f93c62201793abf674166ae9fb7d`
- gate story_brush_monster: `5239ab4e604b95ddb3accb7cca8df756c6a652672a5baae7e03f617d8042ba3d`
- gate story_seed_sprout:  `9bdc35843350ee72c60fa4c85816bbb6cc3a586c3d87b892789cf3e37332d710`
- gate story_bad_all_andthen:    `a9ca7ae4bf8dbef05251527f3162a2ec461132c2c1fe7543ccde606ceec9660a`
- gate story_bad_adjacent_emotion:`f6022eb35cb99627a7c0b996585b9a1ba3f8501327459f9d8155e6cac54c04e8`
- gate story_bad_missing_theme_char:`29980dc556c5afc221a4437357e4f8377236976545feb505be28920738bc55fa`
- manifest_fox_star: `720b84d8aa3b0136a6fb9b703dda757808d4274cea0ce5d73883a5c6dfb7c84c`
- manifest_slide:    `b6b4468570f3cba0a835daff159756c7958c5a1c53da95eea7ad397a320b0635`
**PASS**

### 5. 零网络、无 mock
- 全部为真实代码路径，无远程调用；`shot_spec` 校验器仅读本地 FX 注册表 / sfx manifest（仓库内文件）。
- 测试无 `mock` / `requests` / `httpx` 外部请求；pytest 在断网语义下可跑（仅 import 本地模块 + 读 fixture/json）。**PASS**

### 6. 全链路 dry-run（≥2 部片）+ 可审阅 manifest
`test_full_chain_dry_run` 对 `fox_star` 与 `slide` 走完 `story → gate(PASS) → manifest(OK) → ShotSpec dry-run → 双向绑定 写回shot_rows/回读/重建OK`，并落库 `docs/kids/manifests/manifest_fox_star.json`、`manifest_slide.json`（均 SHA-256 见 4）。**PASS**

### 7. 测试与 lint
- 新增单测 `tests/test_kids_manifest.py`：24 passed。既存 `tests/test_kids_gate.py`（6 passed）、`tests/test_shot_spec_api.py`+`test_shot_spec_render.py`（71 passed）全部不回归；kids_gate/shot_spec 相关测试无回退。
- 3O lint：`PYTHONPATH=$PWD .../python scripts/ci/run_3o_v3_lint.py` → 失败项仍为基线 4 项（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），**未新增失败**（本单新增文件均为 `hevi/kids/` 非 canonical 层，不触发上述 gate；registry 仅 `from import` 不引入新边）。lint 日志未提交仓库。**PASS（失败数=4，与基线持平）**

## git 状态
- 分支 `feat/kids-manifest`，仅 `git add` 本单元创建/修改文件，未 `git add -A`、未 push、未合并、未改写历史。
- 临时文件均在 `.tmp/`（已被 `.gitignore` 忽略），未清理磁盘、未删除 worktree 外任何文件。
- `df /data` 当前剩余约 37G（>5G），未触发 DISK_FULL 中止。

DONE KIDSMANIFEST-R1
