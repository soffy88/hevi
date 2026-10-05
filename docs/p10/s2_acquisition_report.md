# S2 报告 — media probe → 兼容性 → 归一化

```yaml
status: S2 PASS
date: 2026-10-03
chain: Director → p7.AssetRequirement → Acquisition → 归一化 → [S3 seam] → p7.AssetDecision → resolver → MissionExecutor
verification: tests/p10 220 passed · 相邻 601 passed / 2 skipped · ruff clean · mypy clean
```

## 交付

| 落点 | 职责 | 是否新建词汇 |
|---|---|---|
| `p7/constraint_check.py` | **填补 canonical 缺口**:需求硬约束 × 素材事实的判定原语 | 否(用 p7 既有 `KNOWN_CONSTRAINTS` / `CheckOperator` 语义) |
| `creative/autonomous/acquire.py` | 本地素材 Acquirer:探测 → 兼容性 → 归一化 → canonical 候选/证据 | 否(实现既有 `Acquirer` 协议) |

## 复用的既有能力(未重造)

- **探测**:`hevi/qualification/media.py:122 validate_media`(canonical,path-in;`MediaValidation.to_validation_result()` 是「唯一 canonical 结果」)。本包**不 spawn ffprobe** —— `tests/test_p9_1d_mutations.py:134` 明令禁止。
- **观测词汇**:`hevi/artifact/probes.py:33 OBSERVABLE_FIELDS`(闭合集,拼错即报错)。
- **证据形状**:`p7/evidence.py:27 AssetEvidence`;`AssetStatus.AVAILABLE` 必须声明 license(`evidence.py:48-52`)——本包**复用**该规则,不重写。
- **决策**:`p7/asset_intelligence.py:83 AssetDecisionAuthority.decide()`(resolver 既有调用)。

## 关键发现:8 个 constraint key 里 7 个是死字面量

S0 审计已指出,本轮**逐个核实**:`AssetRequirement.constraints` 的 `period / face_required /
resolution / duration / license / locale / aspect` 在 `asset_binding.py` 只被**写入**,
全仓**没有任何**判定「这份素材是否满足这条需求」的原语;只有 `query` 被 `asset_requirement.py:116` 读过。

**所以 `constraint_check.py` 是补 canonical 的洞,不是加新层。**

## 两个必须显式换算的语义(否则静默失败)

1. **类型错配**:constraint 值是字符串(`"1080"` / `"3"`),probe 产出 `float` / `(w,h)` 元组。
   直接 `EQ` **永不匹配** —— 这正是原实现会静默通过一切的原因。已显式换算:
   `duration` 是**下限**、`resolution` 是**最小高度**、`aspect` 需**从 resolution 派生**。
2. **`aspect` 不可直接比较**:像素比必须先约分 —— `1080x1920` 与 `9:16` 是同一比例。
   这是实施期实测抓到的真 bug(首版用精确元组相等,把正确的竖屏素材判为不兼容)。

## fail-closed 三条

- **未观察到 ≠ 通过**:素材事实里没有该约束键 → `satisfied=None`(不可判定),
  `compatible=False`。测试 `test_unobserved_constraint_is_undecidable_not_pass` 锁死。
- **无 license ≠ AVAILABLE**:`normalize_local_asset` 不会因「文件能用」就标 AVAILABLE;
  `LocalAssetAcquirer` 构造时**强制**要求 `license_name`,否则拒绝实例化。
- **坏文件 ≠ 可用**:探测失败 → evidence `REJECTED`、candidate `verified=False` 且带原因。

## S2 边界:不评分

`normalize_local_asset` 产出的 `AssetCandidate` 的 `confidence` 与 `scored_by` **一律留空**,
由 S3 的 canonical scorer 生产。AST 守卫(`test_s3_no_scoring_in_autonomous.py`)仍绿。

## 未做

- stock / procedural / generation 三个来源的 Acquirer(仅 local);
- 候选排序与 `select_candidate` 接线(属 S3);
- `requirement_id` 语义统一(`shot_readiness.py:202` 仍拿 `requirement_id` 比 **asset_ref 列表**,
  是 S0 记录的既有类型混用,本次未扩大也未修)。