# S2/S3 开工门禁 — Q1–Q6 实证答复

- **日期**: 2026-10-03 · **方法**: 读实际代码,不靠命名推断
- **结论**: 6 问已答;其中 **Q4 揭示两个评分体系互不连通**(这是 S2/S3 的真正工作量)。

---

## Q1 — 哪个函数真正拥有 candidate ranking authority?

**答:两个不同层级的 authority,不是同一个。**

| 层 | 权威函数 | 排的是谁 | 位置 |
|---|---|---|---|
| **provider 级** | `evaluate_provider_policy` | **provider**(不是素材候选) | `hevi/provider_policy/policy.py:86`,加权 `:195-201`,排序 `:213-216` |
| **候选级** | `select_candidate` | **同一 requirement 下的候选** | `hevi/production/shot_readiness.py:155` |

- provider 级:权重来自 `ProviderPolicy`(`quality_weight/latency_weight/cost_weight/health_weight/capacity_weight`,policy.py:41-56),候选是 `policy.candidates or PROVIDER_LIMITS`。它回答「**哪个 provider**」。
- 候选级:`select_candidate` 只按**单一 `confidence` 标量**取 max(shot_readiness.py:180),门槛 `REVIEW_CONFIDENCE_FLOOR=0.75`(:152),且要求 `verified`。它回答「**哪个候选**」。
- p7 明确不参与排序:`asset_decision.py:15-25`「does not search, call a provider, or rank」。
- 另有一个**平行**评分:`hevi/providers/scoring.py:139 choose_provider`(独立加权维度 + JSONL 决策日志),与 provider_policy 重叠 —— 这是待 reconciliation 的重复项。

**裁决落点**:S3 的 candidate 级 scoring 应扩展 `shot_readiness.select_candidate` 体系;provider 级继续用 `provider_policy`。**不新建。**

---

## Q2 — AssetFitness 与 provider scoring 的关系?

**答:无关系,是两套不相通的体系。**

`AssetFitness`(`hevi/production/p1_types.py:138`)有 7 维 + 真实权重:

```
entity .25 / action .25 / state .15 / temporal .10 / shot_role .10 / motion .10 / provenance .05
```
（`__post_init__` :155-163 计算 overall;`is_semantic_match(threshold=0.7)` :165）

provider scoring(`policy.py:195-201`)的维度是 **quality/latency/cost/health/capacity** —— 运营指标,不是语义匹配。

**两者零交集**:维度集合不同、加权对象不同(`asset_id+beat_id` vs `provider_id`)、调用链不同。

**更关键**:唯一的 `AssetFitness` 生产者 `calculate_asset_fitness`(`p1_pipeline.py:228`)**硬编码黑洞题材**:

```python
subject_to_asset = {"black hole": "accretion", "accretion disk": "accretion",
                    "event horizon": "accretion", "gravity": "accretion", ...}
motion_score = 1.0 if "orbit" in asset['provenance']['file'] else 0.3
provenance_score = 1.0 if asset['provenance']['source'] == "NASA" else 0.5
```

→ 它是**某一支纪录片的专用打分器**,不是通用候选评分。S2 若复用它,会把「黑洞/ accretion/NASA」写死进通用主干。

---

## Q3 — p7 AssetDecision 是记录还是也含计算?

**答:两者分离,分属两个类。**

| | 角色 | 位置 |
|---|---|---|
| `AssetDecision`(frozen dataclass) | **纯记录**:requirement_id / state / selected_source / provider_decision / confidence / evidence / policy_id / reason | `asset_decision.py:91-187` |
| `AssetDecisionAuthority.decide()` | **计算状态**,但**不算排名** | `asset_intelligence.py:83` |

`decide()` 做的是 fail-closed 顺序判定:provider_decision 缺失 → BLOCKED(`NO_PROVIDER_DECISION`);policy 不可服务 → BLOCKED;声明 provider 但无 selected_source → BLOCKED(`NO_ASSET_OBTAINED`);要求 evidence 而空 → BLOCKED(`NO_ASSET_OBTAINED`/`NO_ASSET_EVIDENCE`);否则 ACCEPTED。

它**消费** `ProviderDecision`(pydantic,权威在 provider_policy),**不生产**排名。类 docstring 自述「Not a registry, repository, selector or scorer」。

---

## Q4 — shot_readiness.select_candidate 是否覆盖全部 canonical dimension?

**答:不覆盖。这是本次门禁最重要的发现。**

`select_candidate`(shot_readiness.py:155-189)只看两个字段:`verified` 与 `confidence`。
`AssetCandidate`(`shot_readiness.py:53-73`)本身也只有 `confidence: float` **单一标量** —— 没有分维度分数。

于是:

```text
AssetFitness(7 维语义分)  ──✗──>  select_candidate(1 维 confidence)  ──>  AssetDecision
        (p1_types/p1_pipeline)         (shot_readiness)                  (p7)
        ↑ 生产者硬编码黑洞题材          ↑ 与左侧无任何连接
```

**两套评分互不相连**:7 维的那套从没喂给选择函数;选择函数用的 `confidence` 由外部直接写入(`AssetCandidate.confidence` 默认 0.0,谁写谁负责,仓内无 canonical 生产者)。

含义:S2/S3 的实质工作是 **reconciliation** —— 让「谁产生候选分数」有唯一答案,而不是再加第五套。

---

## Q5 — 哪些 hard constraints 在 p7,哪些 soft score 在 provider_policy?

| | p7 | provider_policy |
|---|---|---|
| 载体 | `AssetRequirement.constraints`(`KNOWN_CONSTRAINTS` 8 键:period/face_required/resolution/duration/license/locale/aspect/query,`asset_requirement.py:35`) | `ProviderPolicy` 权重与 floor 字段 |
| 语义 | **需求级硬约束**:要什么类型、什么语义角色、quality_floor 0-10、quantity、source_policy(LICENSED_ONLY/PREFERRED_LICENSED/LOCAL_ONLY/ANY_AVAILABLE) | **provider 级准入 + 软分**:health/balance/quota/quality floor 为**硬拒**;quality/latency/cost/capacity 为**加权软分** |
| 执行 | `evaluate_policy`(`asset_policy.py:128`)把需求条款映射到 provider allowance(ALLOWED/BLOCKED) | `evaluate_provider_policy`(:86) |

**注意 p7 的一个重要细节**(`asset_policy.py:101-125`):locality 与 license 都**只读 `ProviderDecision` 的声明字段**,不再从 `provider_id` 前缀猜(`UNRESOLVED` 即 fail-closed)。这是既有的正确做法,S2 必须沿用。

**hard 在两处**:p7 侧=需求条款不可满足;policy 侧=provider 不满足 floor/不可路由。**soft 只有一处**:policy 的 5 维加权。

---

## Q6 — resolver 是否只是把 authority 串起来?

**答:是。** `hevi/creative/autonomous/resolver.py` 全部行为:

1. 无 `provider_decision` → 直接转交 p7(得 BLOCKED),不自选 provider;
2. 有 `provider_decision` → 可选调 `Acquirer` 执行获取,回填 `AssetEvidence` + `selected_source`;
3. 把结果交给 `AssetDecisionAuthority.decide()`;
4. 投影为 `ExecutionReadyResolution`(只读字段)。

它不含任何分数、权重、排序;构造时 `FORBIDDEN_METHODS` 断言挂不上打分函数。**符合裁决。**

---

## 门禁已落码

`tests/p10/test_s3_no_scoring_in_autonomous.py`(5 用例,AST 机械):

- 包内不得出现 `calculate_* / compute_* / score_* / fitness / rank / top_k / argmax / choose_best / pick_best` 类命名;
- 不得出现权重表(weight/coefficient/score_threshold…);
- 不得重新定义 `AssetScore / AssetFitness / CandidateScore / RankedCandidate` 等第 5 套模型;
- `resolver.py` 不得调用 `max/min/sorted/sort`;
- 不得 import `p1_pipeline` / `providers.scoring` / `p1_types`(把 scorer 搬进来)。

**变异验证**:注入 `score_candidate` + `rank_candidates` 后该守卫立即变红
(`SCORING_IN_AUTONOMOUS_PKG: {'resolver.py': [...]}`),移除后恢复绿 —— 守卫真的会失败。

---

## S2/S3 的真实工作量(基于以上发现)

| 项 | 结论 |
|---|---|
| S2 | 加 media probe + candidate/evidence normalization + 接入 p7 `evaluate_policy`。**不碰 scoring。** |
| S3 | **不是新建评分**。是把「`AssetCandidate.confidence` 由谁生产」这件事归一:要么让 `AssetFitness` 成为唯一生产者并把 `calculate_asset_fitness` 的**硬编码题材替换为可注入的匹配器**,要么明确 `confidence` 由 `Acquirer` 生产且不用 AssetFitness。**二选一,需你拍板。** |
| 待 reconciliation | `providers/scoring.py:139 choose_provider` 与 `provider_policy` 的重叠(见 S7)。 |