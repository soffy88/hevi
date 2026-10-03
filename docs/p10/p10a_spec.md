# P10a 状态骨架 SPEC（设计稿 v0.1）

- **范围**: 只建三个正交状态骨架 + Direction 生命周期 + Revision 链。不建 15 语义对象（P10b/c/d 的事）。
- **禁令**: 不揉成一个 enum；不冻结任何 CreativeDirection 语义 schema；不建 `hevi/creative/*`（骨架落点待 P10a 实施时定，优先复用现有 RevisionStore/ApprovalStore 语义）。

## 1. 三个正交状态（各管一件事）

```text
CreativeDirectionState
  ├── ApprovalState      # 人/规则批了什么（不可变 pin）
  ├── CompilationState   # 编译到哪、绑定哪个 revision
  └── VerificationState  #  verdict 结论 + artifact 绑定
```

正交含义：审批通过 ≠ 已编译；已编译 ≠ 已验证；验证结论只引用 artifact hash，不反写审批。

## 2. Direction 生命周期（唯一合法路径）

```text
DRAFT → PROPOSED → REVIEW_REQUIRED → APPROVED → COMPILED → IN_PRODUCTION → VERIFIED
```

- 禁止 `DRAFT → APPROVED`（必须经 REVIEW_REQUIRED；auto 模式需命中规则 + 审计记录）。
- `VERIFIED` 不可原地修改；变更 = 新 revision（见 §3）。

## 3. Revision 链（独立于生命周期）

```text
VERIFIED → REVISION_PROPOSED → APPROVED → INVALIDATE_AFFECTED → COMPILED
```

- `INVALIDATE_AFFECTED` 只失效受影响节点（字段级依赖；A9 缓存缺失时退化为全量，但必须记录 scope=film 降级）。
- unaffected nodes 由输入哈希未变证明保留。

## 4. 六不变量（P10a 必须锁死的证明义务）

1. 状态只能通过合法 transition 改变（矩阵见 §5）。
2. `APPROVED` 是不可静默修改的 immutable revision（内容变 → 批准作废 `APPROVAL_VOID`）。
3. `COMPILED` 必须绑定明确的 direction revision（`compile(revision)` 无 revision 参数即拒绝）。
4. `VERIFIED` 必须绑定最终 artifact/hash（verdict 无 artifact_hash 即拒绝）。
5. revision 不允许破坏 unaffected nodes（保留证明或显式降级记录）。
6. **rejected transition 不得改变当前状态**（Stratum 审计教训：rejected 只能返回错误 + 审计，状态机函数必须是"要么迁移成功、要么状态不动"；实现要求：transition 先校验后提交，单步原子，无中间态落盘）。

## 5. Transition 矩阵（P10a 实施时做成测试表）

| from \ event | propose | request_review | approve | reject | compile | start_production | verify | revise |
|---|---|---|---|---|---|---|---|---|
| DRAFT | PROPOSED | — | — | —(6) | — | — | — | — |
| PROPOSED | — | REVIEW_REQUIRED | — | PROPOSED(6) | — | — | — | — |
| REVIEW_REQUIRED | — | — | APPROVED | PROPOSED(6) | — | — | — | — |
| APPROVED | — | — | — | —(6) | COMPILED | — | — | — |
| COMPILED | — | — | — | —(6) | — | IN_PRODUCTION | — | — |
| IN_PRODUCTION | — | — | — | —(6) | — | — | VERIFIED/保持* | REVISION_PROPOSED |
| VERIFIED | — | — | — | —(6) | — | — | — | REVISION_PROPOSED |

`*` verdict=REVISE/FAIL 时保持 IN_PRODUCTION 并附 verdict（不退回 APPROVED，避免静默重编）。

`—` = 非法 transition，拒绝且状态不动（不变量 6）。`reject` 在任何状态都不改变状态，只记录审计（回到 PROPOSED 的是"发回修改"语义的显式事件，不是 reject 的副作用——实施时二选一并写死）。

## 6. 最小 acceptance（P10a 实施）

```text
A1 state transition matrix        # 全矩阵正/反用例
A2 illegal transition rejection   # 非法迁移拒绝 + 状态不动（断言前后状态相等）
A3 approval immutability          # 改字段后旧批准作废
A4 compiled revision binding      # 无 revision 的 compile 被拒
A5 verification artifact binding  # 无 hash 的 verify 被拒；换文件旧结论作废
A6 revision invalidation boundary # unaffected 保留证明 / 全量降级记录
A7 concurrency / duplicate transition  # 同一 transition 重放幂等；并发写 CONFLICT_STALE_BASE
A8 persistence + reload           # 落盘重载状态一致；中间态不落盘（原子提交）
```

## 7. 非目标（P10b/c/d）

```text
P10b  Direction objects（Brief/Thesis/Benchmark/Treatment）
P10c  Decision / Cue / Beat graph
P10d  Compliance + revision impact（字段级图、early cutoff）
```
