# S3 报告 — 证明只有一个 selection authority（不是「把 scoring 写出来」）

```yaml
status: S3 PASS
date: 2026-10-03
goal: 证明 HEVI 已只有一个真正的 asset selection authority，且 autonomous path 能无歧义调用它
verification: tests/p10 235 passed · 相邻 596 passed · ruff clean · mypy clean (11 source files)
```

## 核心发现：四条 selection 路径，只有一条在生产中

逐条核实调用方（grep 全仓，含 legacy）：

| 路径 | 排的是谁 | 生产调用方 | 判定 |
|---|---|---|---|
| `shot_readiness.select_candidate` | **候选** | **仅测试**（`test_p5_2_grammar`、`test_s3_*`） | **canonical 候选 authority** |
| `provider_policy.evaluate_provider_policy` | **provider** | 3 处真实调用（`api/routers/director_pipeline.py:1771`、`cost/router.py:53`、`tasks/task_service.py:225`） | 不同对象，不是第二选择器 |
| `providers/scoring.choose_provider` | provider | 仅 `layer4_legacy/montage` 引用 | 平行实现，非 canonical |
| `p1_pipeline.calculate_asset_fitness` + max-overall | 候选 | 仅 p1 内部两处自调用，**无外部调用方** | 题材硬编码，登记为**非权威** |

`select_candidate` 当前无生产调用方这一事实**如实记录**：它是唯一符合契约的候选选择入口
（要求 `verified` + `confidence>=0.75` + `scored_by` 有来源），但尚未被生产链接入。
**这不等于「它有问题」——它等于「canonical path 已存在且被锁定，接线是后续工作」。**

## 交付

| 落点 | 职责 |
|---|---|
| `autonomous/identity.py` | `RequirementBinding` / `RequirementBindingSet` —— **纯身份映射**，local ref ↔ canonical p7 id。不评分/不排序/不选/不覆盖 |
| `autonomous/selection.py` | `SelectionAuthority` 声明 + `assert_single_authority()` + 薄转发 `select()` |

**没有创建第二个 Requirement**：canonical identity 仍是 `p7.AssetRequirement.requirement_id`；
`shot_readiness` 保留自己的 `local_ref` 语义，经显式绑定连接。

## 四类硬测试（`tests/p10/test_s3_single_authority.py`，15 用例）

| # | 要求 | 关键断言 |
|---|---|---|
| 1 | identity 全链路不变 | `VIDEO/SCENE` 从 requirement → candidate → decision 不变 |
| 2 | **namespace mismatch 必须显式** | `local_ref != requirement_id`；`covers("ev.png") is False`；未绑定 ref 被 `unbound_local_refs` 暴露；**无隐式宽松匹配** |
| 3 | selection single-authority | 候选级 authority 恰好 1 个；provider 级声明为**不同对象**；非权威路径在册；AST 禁止 autonomous 内定义 select/rank/score（薄转发白名单） |
| 4 | decision provenance | `to_dict()` 含 requirement_id/state/selected_source/confidence/reason/policy_id；`provider_decision` 原样携带（含 `candidate_scores`）；有 `fingerprint()`；拒绝必带 reason；candidate lineage 同时记录 `scored:` 与 `selected:` |

第 2 类是与 S2 两个陷阱**同类**的问题：两边都是 `str`，直接比较能跑、不报错，但语义空间错误，
最后产出一个看起来正常的错误结果。`covers()` 刻意**只接受 canonical id**——把 local ref 传进去
返回 `False`，而不是「宽松匹配成功」。

## 未做（如实登记）

- **生产接线**：`select_candidate` 仍无生产调用方。canonical path 已锁定，接线需要真实 pipeline
  改造（P1+），不在 S3 范围。
- `AssetFitness` 的题材硬编码未替换为可注入匹配器（已在 `NON_AUTHORITATIVE` 登记，
  且 `BlackHoleAssetFitness` 已声明适用域，域外不可用而非低分）。
- stock / procedural / generation 三个 Acquirer 未实现（仅 local）。