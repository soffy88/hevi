# P0-4.0 — Canonical Admission Seam Decision

**Date**: 2026-10-06 · **Baseline**: `d9791d7c` (P0-3)
**Scope**: decision only. No seam is implemented in this phase.

```text
CANONICAL_ADMISSION_SEAM = hevi/provider_policy/policy.py:86 + :234
                            (evaluate_provider_policy + require_provider),
                            anchored at hevi/tasks/task_service.py:1364
```

## Why this seam, and why it is not sufficient

`provider_policy` is the **only** seam that is simultaneously: on the real worker
path, reachable from an HTTP entrypoint, a genuine selection (not a metadata
annotation), capable of refusal (`require_provider:234` raises
`ProviderPolicyError`), and recording its decision durably
(`task_service.py:231` writes `provider_decision` into `config_json`).

It was selected **not because it spans the seven stages** — it does not — but because
it is the only seam positioned between task intake and executor dispatch on every
source that goes through the worker. A facade that is not anchored here would be a
coordinator, which the spec forbids.

It is also insufficient, and that is recorded rather than glossed: **stage 3
(permission) does not exist anywhere in the repository**, and stage 7 (receipt) is
unreachable from this path. Making this seam canonical means closing those two gaps,
not declaring victory.

## The seven stages, as actually implemented

| # | Stage | Real implementation | Production reachability |
|---|---|---|---|
| 1 | Provider selection | `provider_policy/policy.py:86` `evaluate_provider_policy` | **PROD** — `task_service.py:225` (worker, exec-time), `api/routers/director_pipeline.py:1771` |
| 2 | Capability check | three implementations, below | one live: `video/capability_guard.py:153` via `video/kernel_service.py:85` |
| 3 | **Permission** | **none exists** | — |
| 4 | Executor selection | `production/adapters.py:31` `resolve`, dispatched on `production_source` at `task_service.py:1395-1421` | **PROD** |
| 5 | Executor invocation | `creative/layer4/v2v_workflow.py:155-164` and `tongjian/scene_render_avatar.py:305,318,1379,1394` call providers **directly** | 154 files import an out-of-process client |
| 6 | Execution registration | `task_service.py:66` `_start_attempt` | **PROD** — called at `:1370`, *after* policy at `:1364` |
| 7 | Receipt creation | `execution/execute.py:97` `issue_receipt` | **not reachable** — callers are `qualification/framework_local.py:186` and `local_process.py:224`, and those have no entrypoint |

`cost/router.py:53` is dead: zero callers. `creative/autonomous/selection.py:59` is a
metadata string, not code.

## The seven seams

| Seam | Prod callers | Bypass | Registry consulted | Permission | Executor bind | Refusal | Receipt link |
|---|---|---|---|---|---|---|---|
| **`provider_policy/policy.py:86,234`** | `task_service.py:225`, `director_pipeline.py:1771` | all 154 direct-call files; `v2v_workflow.py:159,164` | `PROVIDER_CATALOGUE` `:101` + `PROVIDER_LIMITS` `:118` | **none** | none (returns a string) | `ProviderPolicyError` **raises** `:234` | decision persisted to `config_json` `:231` — **decision only, no artifact** |
| `generation/evidence.py:84` | `generation/qualification.py:189`, `longcat_probe.py:165` | everything | none | none | none | `AdmissionState` enum, no raise | none |
| `creative/autonomous/selection.py:202` | `production/p0_pipeline.py:647` only | `task_service.py:1505`, whole `adapters.py` | none | none | none | `GenerationNotAdmittedError` raises | none |
| `layer4/endpoint_lifecycle.py:462` | `endpoint_execution.py:142`, `task_service.py:2015` | `p0_pipeline.py:647`, `task_service.py:1505` | `DeclarativeEndpointDefinition` rows (`:117`) — protocol slots, **not providers** | none | `execute_endpoint` | `AdmissionVerdict(admitted=False)` — **returns, does not raise** | `CallLedgerStore` `:757` |
| `layer4/plan_projection.py:222,252` | `api/routers/authorities.py:854` | `task_service.py:2015` re-implements it inline | same | none | none | `AdmissionVerdict3.decision` str | none |
| `video/capability_guard.py:153` | `video/kernel_service.py:85` | `v2v_workflow.py`, `scene_render_avatar.py` | `ProviderRegistry` first `:174`, `PROVIDER_LIMITS` `:170` | none | precedes kernel dispatch | `CapabilityError` raises | none |
| `runtime/provider/provider_probe.py:67,76` | **none** | n/a | `PROVIDER_SPECS` | none | none | never raises (`:71-73`) | none |

Five independent failure vocabularies: `ProviderPolicyError`, `AdmissionState`,
`GenerationNotAdmittedError`, `AdmissionVerdict`, `AdmissionVerdict3`, plus
`CapabilityError` and `RuntimeAvailability`.

**Rejected as canonical:**
- `generation/evidence.py:84` — both callers are qualification/probe tooling.
- `creative/autonomous/selection.py:202` — one caller; `p1→p2` is not wired to a route.
- `plan_projection.py:222,252` — API-only, and `task_service.py:2015` **duplicates
  its logic inline**, so adopting it means adopting a second copy.
- `runtime/provider/provider_probe.py:67` — zero production reachability.
- `video/capability_guard.py:153` — genuinely the last gate before video invocation,
  but it guards video only, and it is shadowed (blocker 4).

## The ten known blockers, each verified

**1 — Direct `/run` bypass. VERIFIED, and worse than a route name.** `POST
/authorities/endpoints/{name}/run` creates a task with
`video_provider="declarative_endpoint"`. `_run_task_impl` applies provider policy
over a **fixed source set** (`task_service.py:1337-1362`) that does **not** include
`declarative_endpoint`, then dispatches at `:1394` to `_run_declarative_endpoint:711`,
which checks only `state != "enabled"` (`:733`) and never calls
`check_declared_capability`. Eleven sibling `/run` routes exist
(`longcat.py:103`, `tongjian.py:826`, `openshorts.py:36`, `freezone.py:68`,
`montage.py:76,132`, `explainer.py:757`, `embrace_runtime.py:290`, `narrator.py:25`).

**2 — Seven seams coexist. VERIFIED**, each with its own failure type (table above).

**3 — Registries: six, not five — and not seven.** `providers/registry.py:8` is a
**re-export** of `obase.provider_registry.ProviderRegistry`; the file defines no class
of its own (`rg -c "^class "` → 0). The provider-facing set is:

1. `providers/registry.py:8` `ProviderRegistry` (re-export, holds live callables)
2. `providers/facts.py:356` `PROVIDER_CATALOGUE` (declared facts)
3. `provider_policy/runtime.py:38` `PROVIDER_SPECS` (spec/health, HTTP `/status`)
4. `providers/runtime_specs.py:247` `RUNTIME_SPECS` (local render recipes)
5. `video/capability_guard.py:27` `PROVIDER_LIMITS` (numeric ceilings)
6. `production/adapters.py:17` `ProductionAdapterRegistry` (`production_source` → coroutine)

**Two corrections to earlier audits.** P0-1 said five and located `ProviderRegistry`
at `:24`; it is at `:8` and is a re-export. This phase initially counted seven by
including a supposed `EndpointRegistry` in
`layer4/endpoint_lifecycle.py` — **that class does not exist**. What exists there is
`DeclarativeEndpointDefinition:117`, a protocol slot describing URL shapes and auth
conventions. It is not a provider registry and counting it as one inflated the
number. `ProductionAdapterRegistry` is counted because it resolves to callables, which
is the property that makes it a registry rather than a table — but it routes
`production_source`, not providers, so it is the sixth rather than a duplicate of the
first.

**4 — `PROVIDER_LIMITS` shadowing. VERIFIED, and partial in a way P0-1 missed.**
`capability_guard.py:167` hard-fails any provider absent from `PROVIDER_LIMITS`
*before* the registry is consulted, so `ProviderRegistry` can only ever narrow. And
`:174` overrides **only `modes`** — `max_resolution` `:187`, `max_duration_s:193` and
`fps_options:199` read `PROVIDER_LIMITS` unconditionally. **The live registry has zero
effect on three of four checks.**

**5 — Unknown failure → `RETRY_TARGET`. VERIFIED.** `repair.py:24-34` `FAILURE_TO_KIND`
maps 8 codes; `:49` defaults to `RepairKind.RETRY_TARGET`. Same default at
`v2v_workflow.py:147`. An unrecognised failure is therefore treated as safely
retryable — the retry is operationally convenient, and that is exactly the reasoning
the spec forbids.

**6 — Capability/permission disagreement: there is no permission layer.** Capability
can pass and nothing between it and invocation checks tenancy, budget, or credit.
`auth/dependencies.py:65` `require_admin` is route-scoped and does not run on the
worker path. `constraints/` is delivery verification (`verdict.py:37`), not
authorization. Budget is checked at **create** time (`task_service.py:1177,1181`)
against a **pre-selection** estimate — policy runs later at exec time (`:1364`) — and
settled only after (`:1046`, `:1093`).

**7 — Qualification unenforced on production. VERIFIED.** `hevi/qualification/*` is
imported by `hevi/creative/autonomous/acquire.py` only, and only `media.py`. The
runners (`framework_local.py`, `local_process.py`) have **zero** importers under
`hevi/api`, `hevi/tasks`, `hevi/queue`. Nothing on the worker path consults a
qualification verdict before invoking a provider.

**8 — Refusal creating execution state. VERIFIED, and P0-1's "no attempt row" was
incomplete.** Correct part: policy refusal at `:1364` precedes `_start_attempt:1370`,
and `_finish_attempt:128` returns early when `task["_attempt_id"]` is absent, so no
attempt row is created. Incomplete part: `create_task:1146` has already persisted the
task row, and `budget_repo.reserve_attempt:1222` has already reserved budget with a
`budget_attempt_id` written into `config_json:1268`. Separately,
`admit_regeneration_media:1985` builds its declaration from
`PROVIDER_LIMITS.max_resolution` only. Two fail-open paths, both verified by reading
the function:

- if the provider is absent from `PROVIDER_LIMITS` it returns `()` at `:1987` —
  *"no descriptor: nothing canonical to admit against"* — which is admission-by-
  absence. A provider HEVI cannot describe is admitted because HEVI knows nothing
  about it.
- on success it returns `tuple(reasons)` at `:2017` after `_ = shot_ids`, and
  `reasons` is provably empty on any path that reaches it: every non-empty case raises
  at `:2016`. So the return is **always** `()`.

All three callers (`api/routers/tasks.py:442,2032,2286`) use `except ValueError` and
**discard the return value**, so in practice the always-`()` return is inert. The real
defect is the `:1987` early return: it is the one path where a refusal *should* be
raised and is not.

**9 — Unknown = retryable. VERIFIED** (blocker 5).

**10 — Receipt linkage. VERIFIED BROKEN.** `issue_receipt` is called at
`framework_local.py:186` and `local_process.py:224`, but those modules have no
entrypoint. `_receipt` (`artifact_verification.py:457`) is reachable only from
`scripts/qualification/`. `generation/backend.py:107` `run_generation` has no
production caller. **No admission decision and no execution on the API or worker path
produces a receipt.** The only durable record is the attempt row
(`_start_attempt:66`) plus `CallLedgerStore` (`:757`), which record that a task ran
without recording what was admitted.

## What the implementation phase must absorb

A facade is acceptable **only** as a thin absorber of the existing position at
`task_service.py:1364`. It must not become a coordinator. Concretely:

1. **Absorb stage 2** by *calling* `video/capability_guard.py:153` and
   `layer4/endpoint_lifecycle.py:462` — two live vocabularies, not reimplemented.
2. **Build stage 3.** Nothing exists. Without this the seam is theatre: a facade
   that checks capability but not tenancy or budget is the same hole with a new name.
3. **Absorb stage 4** by routing `production/adapters.py:31` through the seam, and add
   `declarative_endpoint` to the gated source set (blocker 1).
4. **Absorb stage 5.** 154 direct-call files exist; `v2v_workflow.py:155-164` and
   `tongjian/scene_render_avatar.py:305,318,1379,1394` are the named priorities.
5. **Keep stage 6 ordering** — `_start_attempt` must stay *after* admission, which is
   already correct and must not regress.
6. **Give stage 7 a production caller.** `issue_receipt` exists and is fail-closed
   (`execution/models.py:149-182`); it needs a caller on this path, not a rewrite.
7. **Fix `admit_regeneration_media:1987`**, which admits by absence when a provider is
   not in `PROVIDER_LIMITS`. The always-`()` return at `:2017` is inert (callers
   discard it), so this is a one-line refusal, not a redesign.
8. **Make `to_kind` fail closed** (blocker 5) — unknown must not become `RETRY_TARGET`.
9. **De-duplicate `PROVIDER_LIMITS` against `ProviderRegistry`** so the live registry
   governs all four checks (blocker 4).

## Gate readiness

| Gate | Ready? |
|---|---|
| `ADMISSION_CANONICAL_SEAM_IDENTIFIED` | **PASS** — one seam designated, six rejected with reasons |
| `PROVIDER_REGISTRY_SINGLE_SOURCE` | BLOCKED — 7 registries; §10 of the implementation plan |
| `CAPABILITY_CHECK_FAIL_CLOSED` | PARTIAL — `capability_guard` raises; shadowed on 3 of 4 checks |
| `PERMISSION_CHECK_FAIL_CLOSED` | **BLOCKED** — the layer does not exist |
| `EXECUTOR_QUALIFICATION_ENFORCED` | **BLOCKED** — no production caller of any qualification verdict |
| `DIRECT_EXECUTION_BYPASS_CLOSED` | **BLOCKED** — `declarative_endpoint` + 11 sibling routes |
| `UNKNOWN_FAILURE_FAIL_CLOSED` | **BLOCKED** — `repair.py:49`, `v2v_workflow.py:147` |
| `FAILED_ADMISSION_NO_EXECUTION` | PARTIAL — no attempt row; budget already reserved |
| `EXECUTION_RECEIPT_BOUND` | **BLOCKED** — no receipt on this path |

The first gate passes. The remaining eight are the work, and five of them are blocked
on something that does not yet exist rather than on something that is wrong.

## Two corrections to earlier audits

`ProviderRegistry` is a **re-export of `obase.provider_registry.ProviderRegistry` at
`providers/registry.py:8`**, not a class defined there — P0-1 recorded it as a class at
`:24`. The provider-facing registry count is **six**.

An intermediate version of this document said seven, counting a supposed
`EndpointRegistry` in `layer4/endpoint_lifecycle.py`. No such class exists; the module
defines `DeclarativeEndpointDefinition:117`, which describes protocol slots rather
than providers. The count was corrected to six after reading the module, and the
correction is recorded here because the first count was my error, not a repository
defect.

P0-1's `FAILED_ADMISSION_NO_EXECUTION: PARTIAL` under-reached. No attempt row is
created, which is correct — but `create_task:1146` persists the task and
`:1222` reserves budget before admission runs at all, so "no execution state" is not
the whole truth.

---

## P0-4.1 — permission/tenancy phase report

`PERMISSION_CHECK_FAIL_CLOSED` moves from BLOCKED to **PARTIAL**. The authority
exists and refuses; what does not exist is a tenancy model behind it.

### What landed

`hevi/provider_policy/permission.py` adds the layer. `evaluate_permission` checks,
in order: principal, tenant, scope-configured, provider, capability, operation,
budget authority, budget ceiling, execution target. The first refusal short-circuits
the reason string but every check is still recorded, so the decision object shows
which checks ran rather than only why they failed.

`TaskService._apply_provider_policy` (`task_service.py:1364`) asks permission
**before** the `PgPool` guard and **before** `_start_attempt`. Placing it under the
pool guard — where the provider *policy* still lives — would have made permission a
bypass for every local-mode deployment, which is the same
"route-was-authenticated-therefore-worker-may-execute" hole this document exists to
close. Local pool and PostgreSQL deployments are now judged identically.

A decision is persisted to `config_json.permission_decision` on both allow and
refuse, because a refusal that exists only in a log line cannot be audited, and a
decision record that only records refusals cannot answer why a task *ran*.

Budget is untouched by a permission refusal: the reservation stays `held`, nothing is
settled or released, because no execution occurred. An admission verdict is not a
cost measurement, so this layer never settles.

### Two defects found while writing it

The first version wrote the decision into `task["config_json"]`, which is splatted
as `**kwargs` into `orchestrate_longvideo` (`task_service.py:1590`). That turns an
audit field into a required render parameter, and adds a new one each time the
decision gains a field. The persisted row and the in-memory config are now
deliberately different objects; `test_decision_never_reaches_orchestration_kwargs`
pins it.

The scope grammar originally let a tenant scope grant `admin` by naming it, which
contradicted its own comment and would have handed admin capability to whoever edits
`admission_tenant_scopes` — a capability `require_admin` assumes only an explicit
admin route can reach. `OperationKind.ADMIN` is now refused unconditionally at this
seam. `test_admin_operation_denies_even_under_a_deliberately_wide_scope` pins it.

### Why the gate is still not PASS

There is no tenancy model. `hevi/auth/models.py` defines `users` and nothing else;
`workspace_id` appears only as an optional column in video-intelligence tables. So
the seam can only compare a caller-supplied tenant against operator-declared
`admission_tenant_scopes`. It answers "is this tenant permitted", never "does this
principal belong to this tenant" — the second question is the one that is actually
an authorization question.

To keep the API usable under fail-closed, `LongVideoRequest` gained an optional
`workspace_id`, plumbed into `config_json` (`api/routers/tasks.py:39`). It is
caller-declared, not server-derived, and that is the debt this gate is recording.
A task created without one is denied, which is correct and also means an
unconfigured deployment runs nothing.

`PERMISSION_CHECK_FAIL_CLOSED` stays **PARTIAL** on that basis. It becomes PASS when
a tenant is resolved from the authenticated principal against a real membership
table, and this field can be deleted rather than trusted.
