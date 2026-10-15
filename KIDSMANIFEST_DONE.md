# KIDSMANIFEST 单元完成报告 (KIDSMANIFEST-R2)

## 范围与依据
- 单元 K1：幼儿故事闸门 `kids_story_gate` + `KidsConsistencyManifest`（绑定 ShotSpec）R2 完整修复。
- 依据：`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` 第 3 节（3.1 片单、3.2 P1/P2、3.3 schema 与绑定规则）与第 4 节 K1；`KIDSMANIFEST_FIX.md`。
- 已完整阅读 `KIDS_ANIME_DIRECTION.md` 与 `CAPABILITY_CONTRACT.md` 并遵守。
- 许可：仅吸收 Renoise 方法论（无 LICENSE），未复制其原文/代码；BeefTV(MIT) 本次未 vendor。

## 交付文件
- `hevi/quality/kids_gate.py`：扩展 `FORBIDDEN_WORDS` 词表（单源真理）。
- `hevi/kids/story_gate.py`：实现 FIX-1..6（R8 内容安全硬拦截、R9 告别拍互动问句、R10 复述拍主题+动作、R7 口语语言锁真校验、R4 情绪缺失闸门、R6 固定角色一致性与 story↔manifest 交叉校验、R1 logline 确定性生成与公式校验、复用 `ContinuityEngine`）。
- `hevi/kids/consistency_manifest.py`：实现 FIX-7..13（M6 角色锚点锁定、M3 语言校验、M5 时长绑定与 manifest_from_task_specs 报错、M7 镜号唯一与 M2 切点生成、M4 递归扫描全部文本字段 @引用、M0 错误分类与 shot_spec 未知字段拦截、attach_to_task_shot_rows strict）。
- `hevi/kids/prompt_compile.py`：实现 FIX-14（Style Bible 四段逐字前置编译与校验）。
- `hevi/capabilities/registry.py`：实现 FIX-16（`CapabilityError` + jsonschema `params_schema` 校验）。
- `hevi/api/routers/capabilities.py` + `hevi/api/main.py`：实现 FIX-15（`GET /api/capabilities` 挂载）。
- `tests/test_kids_manifest.py`、`tests/test_kids_prompt_compile.py`、`tests/test_capabilities_api.py`：增补全覆盖单元测试。

## 验收标准实测结果

### 1. 独立核验 Probe 结果（`audit/kidsmanifest/verify_r1/probe_counterexamples.py`）
命令（`PATH=$HOME/.local/bin:$PATH JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python audit/kidsmanifest/verify_r1/probe_counterexamples.py .tmp/probe_r2.json`）：
- 输出：总计 45 个用例中，除 M13、M15（K2 范围，按契约可保持 OK）外，**MISS 数为 0**（`Total items: 45, Misses (excl M13/M15/B4): 0`）。
- G0 四部试点 story 全部 PASS，G1–G8 坏样本全部精准拦截（FAIL/WARN）。
- manifest 各项坏样本（M1–M12, M14）全部正确失败。
- 注册表能力调用与参数校验、API 路由契约、双向绑定全部通过。

### 2. 确定性
- 双进程 SHA-256 哈希比对一致 (`D1_determinism_xproc` 通过)。

### 3. 零网络、无 mock
- 纯本地真实代码路径与 ffmpeg/PIL 产物，断网可跑，无任何远程调用与 mock。

### 4. 测试与 lint
- pytest（107 passed）：`tests/test_kids_manifest.py`、`tests/test_kids_gate.py`、`tests/test_shot_spec_api.py`、`tests/test_shot_spec_render.py`、`tests/test_kids_prompt_compile.py`、`tests/test_capabilities_api.py` 全部通过。
- 3O lint：失败数=4，与基线 4 项一致，无新增失败项。

## git 状态
- 分支 `feat/kids-manifest`，仅 `git add` 本单元创建与修改文件，未 push、未合并。

DONE KIDSMANIFEST-R2
