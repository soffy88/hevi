# KIDSMANIFEST 单元完成报告 (KIDSMANIFEST-R3)

## 范围与依据
- 单元 K1：幼儿故事闸门 `kids_story_gate` + `KidsConsistencyManifest`（绑定 ShotSpec）R3 修复完成。
- 依据：`KIDSMANIFEST_FIX.md`（FIX-A R8 内容安全：去单字子串匹配、采用词/短语匹配、白名单与规则化有害词库、否定/教育语境不误杀；FIX-B `attach_to_task_shot_rows` 默认 strict=True 抛错）。
- 许可：仅吸收 Renoise 方法论（无 LICENSE），未复制其原文/代码。

## 交付与修复文件
- `hevi/kids/data/kids_safety_rules.json`：合规词库与白名单数据文件（暴力伤害、恐吓、死亡、霸凌辱骂、危险行为、陌生人诱拐、毒/炸/火、成人、品牌、复合白名单）。
- `hevi/quality/kids_gate.py`、`hevi/kids/story_gate.py`：实现 FIX-A：取消单字子串模糊误杀，采用词/短语库匹配，叠加白名单与否定/教育语境窗口判定（不误杀“打开/打扫/打伞/打招呼”及“不打人/不能跟陌生人走”等）。
- `hevi/kids/consistency_manifest.py`：实现 FIX-B：`attach_to_task_shot_rows` 默认 `strict=True`，孤儿任务行严格抛出 `ShotIndexMismatchError`。
- `tests/test_kids_manifest.py`、`audit/kidsmanifest/verify_r2/extra.py`：增补 12 条参数化测试（3 误杀 + 1 正常断言 PASS，7 漏杀断言 FAIL，2 否定语境断言非 FAIL）及 strict 模式覆盖。

## 验收标准实测结果

### 1. 独立核验 Probe 与 Extra 结果
- `audit/kidsmanifest/verify_r2/extra.py` 运行实测：
  - 误杀 3 条 + 正常 1 条全部 PASS (`fp_open`, `fp_sweep`, `fp_umbrella`, `fp_hot`)。
  - 漏杀 7 条全部精准拦截 FAIL (`fn_hit`, `fn_kick`, `fn_monster`, `fn_poison`, `fn_bomb`, `fn_stranger`, `fn_insult`)。
  - 否定语境正确 PASS/非 FAIL。
- Probe 45 项中 B4 探针在默认 `strict=True` 下正确报错 `ShotIndexMismatchError`。

### 2. 测试与确定性
- pytest（39/39 passed）：`tests/test_kids_manifest.py` 全通过。
- 确定性双进程 SHA-256 哈希比对一致 (`test_determinism_via_subprocesses` 通过)。

### 3. 安全规则
- 仅修改本地 worktree 允许文件，无磁盘清理，无 rm 已跟踪文件，CPU 离线运行，无付费 API，无 mock。

DONE KIDSMANIFEST-R3
