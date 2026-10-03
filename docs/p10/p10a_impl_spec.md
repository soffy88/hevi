# P10a — Creative Direction State Skeleton

## Implementation Specification

Status: IMPLEMENTATION SPEC (FROZEN 2026-10-03)
Scope: P10a only
Prerequisite: P10-S PASS / G0 CONDITIONAL PASS
Out of scope: P10b / P10c / P10d
Schema freeze: only P10a state contracts may be frozen

---

## 1. Objective

P10a 的唯一目标：

> 建立 Creative Direction 的持久化、原子、可恢复、不可越权的状态骨架。

P10a 不实现完整 Creative Direction 语义。

不得实现：

* BenchmarkSet
* Treatment
* CueMap
* SoundDirection
* CreativeProgram
* Compliance Engine
* Revision Impact Engine
* Creative Memory
* Direction Compiler

P10a 只证明：

```text
Direction Revision
        ↓
State Machine
        ↓
Approval
        ↓
Compilation
        ↓
Production
        ↓
Verification
```

状态不会被非法迁移、隐式修改、重复提交或失败操作污染。

---

## 2. Existing Authority Boundary

P10a 不创建第二套：

* Approval Authority
* Revision Authority
* Artifact Authority
* Verdict Authority

必须首先复用或通过 adapter 接入现有 HEVI authority。

新增代码只能负责：

```text
P10 Direction State
        +
P10 transition policy
        +
P10 persistence adapter
```

不得接管现有生产 authority。

---

## 3. State Model

P10a 使用三个正交状态维度。

### 3.1 Direction Lifecycle

```text
DRAFT
  ↓
PROPOSED
  ↓
REVIEW_REQUIRED
  ↓
APPROVED
  ↓
COMPILED
  ↓
IN_PRODUCTION
  ↓
VERIFIED
```

每次 transition 必须：

```text
old_state
→ validate
→ atomic mutation
→ event
→ resulting_state
```

不得出现：

```text
old_state
→ partial mutation
→ exception
```

---

## 4. Review Semantics

这是 P10a 的强制语义。

### REJECT

`REJECT` 是纯拒绝。

```text
REVIEW_REQUIRED
       |
       +-- REJECT
       |
       v
REVIEW_REQUIRED
```

状态不改变。

必须产生：

```yaml
ReviewEvent:
  action: REJECT
  revision:
  reason:
  actor:
  command_id:
```

### REQUEST_CHANGES

`REQUEST_CHANGES` 是显式发回。

```text
REVIEW_REQUIRED
       |
       +-- REQUEST_CHANGES
       |
       v
PROPOSED
```

二者绝不能共用 `reject()` 语义。

---

## 5. Revision State

Revision 与 Direction lifecycle 正交。

已 VERIFIED 的 revision 不允许原地修改。

```text
VERIFIED
    ↓
REVISION_PROPOSED
    ↓
APPROVED
    ↓
INVALIDATE_AFFECTED
    ↓
COMPILED
```

旧 revision 永久保留。

禁止：

```python
direction.revision += 1
```

这种 destructive mutation。

必须创建新的 revision identity。

---

## 6. Minimal Data Contract

### DirectionState

```yaml
DirectionState:
  project_id:
  direction_id:
  revision:
  lifecycle:
    DRAFT
    PROPOSED
    REVIEW_REQUIRED
    APPROVED
    COMPILED
    IN_PRODUCTION
    VERIFIED
  revision_state:
  created_at:
  updated_at:
  version:
```

P10a 不要求在该对象中加入完整 CreativeDirection 内容。

### TransitionCommand

```yaml
TransitionCommand:
  command_id:
  project_id:
  direction_id:
  revision:
  action:
  expected_state:
  actor:
  reason:
  idempotency_key:
```

`expected_state` 是 optimistic concurrency guard。

### TransitionEvent

```yaml
TransitionEvent:
  event_id:
  command_id:
  project_id:
  direction_id:
  revision:
  from_state:
  action:
  to_state:
  actor:
  reason:
  created_at:
```

Event 必须能够证明：

```text
谁
对哪个 revision
从什么状态
执行了什么动作
产生什么状态
```

---

## 7. Transition Matrix

### Allowed

| From              | Action           | To                |
| ----------------- | ---------------- | ----------------- |
| DRAFT             | PROPOSE          | PROPOSED          |
| PROPOSED          | SUBMIT_REVIEW    | REVIEW_REQUIRED   |
| REVIEW_REQUIRED   | REJECT           | REVIEW_REQUIRED   |
| REVIEW_REQUIRED   | REQUEST_CHANGES  | PROPOSED          |
| REVIEW_REQUIRED   | APPROVE          | APPROVED          |
| APPROVED          | COMPILE          | COMPILED          |
| COMPILED          | START_PRODUCTION | IN_PRODUCTION     |
| IN_PRODUCTION     | VERIFY           | VERIFIED          |
| VERIFIED          | CREATE_REVISION  | REVISION_PROPOSED |
| REVISION_PROPOSED | APPROVE          | APPROVED          |

`REJECT` 与 `REQUEST_CHANGES` 必须分别实现。

---

## 8. Forbidden Transitions

至少覆盖：

```text
DRAFT → APPROVED
DRAFT → COMPILED
DRAFT → VERIFIED

PROPOSED → APPROVED
PROPOSED → COMPILED

REVIEW_REQUIRED → COMPILED
REVIEW_REQUIRED → VERIFIED

APPROVED → PROPOSED
APPROVED → REVIEW_REQUIRED
APPROVED → VERIFIED

COMPILED → APPROVED
COMPILED → VERIFIED

IN_PRODUCTION → APPROVED

VERIFIED → DRAFT
VERIFIED → PROPOSED
VERIFIED → APPROVED
```

任何 forbidden transition：

```text
state unchanged
event unchanged
revision unchanged
```

---

## 9. Six Core Invariants

### I1 — Legal Transition

任何状态变化必须属于 transition matrix。

### I2 — Atomic Transition

一次 command：

```text
validate
+
state mutation
+
event
```

必须原子完成。

如果失败：

```text
state unchanged
event unchanged
```

### I3 — Rejected Does Not Mutate Lifecycle

```text
REVIEW_REQUIRED
--REJECT-->
REVIEW_REQUIRED
```

只能增加 rejection evidence。

### I4 — Revision Immutability

`APPROVED / COMPILED / IN_PRODUCTION / VERIFIED` revision 不允许原地修改。

### I5 — Artifact Binding

进入：

```text
COMPILED
```

必须绑定：

```text
direction_revision
compile_receipt
```

进入：

```text
VERIFIED
```

必须绑定：

```text
artifact_hash
verification_receipt
```

不能只有：

```text
status = VERIFIED
```

### I6 — Failed Transition Has Zero State Mutation

任何：

```text
invalid transition
stale revision
wrong expected_state
duplicate command
persistence failure
```

都不得改变 lifecycle state。

这是 P10a 对 Stratum 类状态污染问题的明确防线。

---

## 10. Idempotency

所有 transition command 必须具有：

```text
command_id / idempotency_key
```

重复提交同一 command：

```text
first:
state mutation

second:
same resulting state
no duplicate mutation
```

禁止：

```text
DRAFT
→ PROPOSED
→ PROPOSED
```

产生两个 transition event。

---

## 11. Concurrency

必须支持 optimistic concurrency。

Command：

```yaml
expected_state: REVIEW_REQUIRED
```

如果实际：

```text
APPROVED
```

则：

```text
CONFLICT
```

结果：

```text
state unchanged
no transition event
```

禁止 last-write-wins。

---

## 12. Persistence

P10a 必须验证：

```text
create
→ transition
→ process restart
→ reload
→ same state
```

不能只使用：

```text
in-memory dict
```

作为 acceptance implementation。

存储必须复用现有 HEVI storage authority。

如果现有 storage 无法满足 atomic transition：

> 先补 storage capability，不得偷偷建立第二套 persistent ledger。

---

## 13. Recovery

进程在 transition 前后任意时点异常退出时：

恢复后必须得到合法状态。

禁止：

```text
state = APPROVED
event = REVIEW_REQUIRED
```

或者：

```text
event = APPROVED
state = REVIEW_REQUIRED
```

这种 state/event divergence。

---

## 14. API Surface

P10a 最小 API：

```python
create_direction_state()

get_direction_state()

transition_direction()

approve_direction()

reject_direction()

request_changes()

get_transition_history()

create_revision()

reload_direction_state()
```

其中：

```python
reject_direction()
```

与：

```python
request_changes()
```

必须是不同操作。

---

## 15. Implementation Boundary

推荐结构：

```text
hevi/creative/
    state.py
    state_machine.py
    transition.py
    repository.py
    events.py
    errors.py
    revision.py
```

但只有在 Gate 0 的 existing authority audit 确认没有重复 owner 后才能创建。

如果已有对应 authority：

```text
adapter > duplicate implementation
```

优先级：

```text
reuse existing
    >
adapter
    >
extend existing
    >
new P10 component
```

---

## 16. Tests

测试必须是真实 state/repository chain。

禁止只测纯函数 matrix。

### A1 — Transition Matrix

覆盖全部 allowed transitions。

### A2 — Illegal Transition

每个关键 forbidden transition 至少一个测试。

断言：

```python
state_before == state_after
```

### A3 — Reject Semantics

```text
REVIEW_REQUIRED
→ REJECT
→ REVIEW_REQUIRED
```

并验证 rejection event。

### A4 — Request Changes

```text
REVIEW_REQUIRED
→ REQUEST_CHANGES
→ PROPOSED
```

证明与 REJECT 不同。

### A5 — Atomic Failure

模拟 persistence failure。

断言：

```text
no state mutation
no partial event
```

### A6 — Artifact Binding

COMPILE 无 receipt：

```text
FAIL
```

VERIFY 无 artifact hash：

```text
FAIL
```

### A7 — Revision Immutability

VERIFIED revision 尝试修改：

```text
FAIL
```

必须创建新 revision。

### A8 — Concurrency

两个 command：

```text
expected_state=REVIEW_REQUIRED
```

只有一个可以改变状态。

另一个：

```text
CONFLICT
```

### A9 — Idempotency

相同 command 提交两次：

```text
one mutation
one transition event
same resulting state
```

### A10 — Persistence Reload

```text
transition
→ shutdown
→ reload
→ assert state
```

### A11 — Recovery

故障注入：

```text
before mutation
during persistence
after event
```

验证不会产生非法状态。

### A12 — Revision Chain

```text
revision 1
→ VERIFIED

revision 2
→ REVISION_PROPOSED
```

revision 1 必须保持 immutable。

---

## 17. Acceptance Fixtures

至少三个真实 fixture：

### Fixture A

```text
DRAFT
→ PROPOSED
→ REVIEW_REQUIRED
→ APPROVED
→ COMPILED
→ IN_PRODUCTION
→ VERIFIED
```

### Fixture B

```text
REVIEW_REQUIRED
→ REJECT
→ REVIEW_REQUIRED
→ REQUEST_CHANGES
→ PROPOSED
```

### Fixture C

```text
VERIFIED
→ CREATE_REVISION
→ REVISION_PROPOSED
→ APPROVED
→ COMPILED
```

并验证旧 revision 完整保留。

---

## 18. Acceptance Gates

P10a 必须全部 PASS：

```text
A1 transition matrix
A2 illegal transition rejection
A3 reject semantics
A4 request-changes semantics
A5 atomic transition
A6 approval immutability
A7 compile binding
A8 verification binding
A9 revision immutability
A10 concurrency
A11 idempotency
A12 persistence/reload
A13 recovery
A14 transition history
```

任何一个 FAIL：

```text
P10a = NOT ACCEPTED
P10b/c/d = BLOCKED
```

---

## 19. Required Evidence

实施必须生成：

```text
docs/p10/p10a_acceptance.md
```

至少包含：

```text
commit
test command
test count
ruff
type-check
transition matrix result
atomicity result
concurrency result
idempotency result
persistence result
recovery result
revision immutability result
```

不能只报告：

```text
pytest passed
```

---

## 20. Required Negative Evidence

报告必须明确记录：

```text
REJECT does not mutate lifecycle
invalid transition does not mutate state
stale command does not mutate state
duplicate command does not duplicate event
failed persistence does not leave partial state
verified revision cannot be modified
```

---

## 21. P10a Exit Criteria

全部满足：

```text
14 acceptance gates PASS
+
real persistence
+
real transition history
+
atomic mutation
+
idempotency
+
concurrency
+
recovery
+
revision immutability
```

则：

```text
P10a = PASS
```

否则：

```text
P10a = NOT ACCEPTED
```

---

## 22. Explicit Non-Goals

P10a 完成后仍不得声明：

```text
Creative Direction Runtime complete
```

P10a 只证明：

```text
Creative Direction
can exist as a durable,
versioned,
approval-controlled,
atomic state machine.
```

以下继续保持 BLOCKED：

```text
P10b Direction Objects
P10c Cue / Decision Graph
P10d Compliance / Revision Impact
```

---

## 23. Implementation Order

严格：

```text
1. inspect existing ApprovalStore / RevisionStore / artifact store
2. resolve ownership
3. implement state contract
4. implement transition matrix
5. implement persistence
6. implement atomicity
7. implement idempotency
8. implement concurrency
9. implement revision immutability
10. run A1–A14
11. generate acceptance report
12. only then evaluate P10a PASS
```

禁止：

```text
先建 hevi/creative/*
再寻找 existing authority
```

---

## 24. Final Gate

```text
P10-S PASS
      ↓
P10a Implementation
      ↓
A1–A14
      ↓
ALL PASS
      ↓
P10a PASS
      ↓
P10b DESIGN ALLOWED
```

如果 A1–A14 中任何一个失败：

```text
P10a NOT ACCEPTED
P10b/c/d BLOCKED
```

P10a 的核心原则：

> **状态可以演进，但历史不能被重写；拒绝可以发生，但拒绝本身不能偷偷改变生命周期；失败可以返回，但失败不能留下半个状态。**
