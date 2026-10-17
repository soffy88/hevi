# HEVI P6 — Runtime Boundary

## The port already existed

P6.0 shipped the whole boundary in `hevi/production/p6/runtime.py`:

```python
@runtime_checkable
class ProductionRuntimePort(Protocol):
    runtime_id: str
    def submit(self, intent, source_material, constraints) -> Any: ...
```

and a `RuntimeBoundary` that **delegates and never produces locally**, raising
`RuntimeNotBoundError` rather than falling back to a built-in pipeline — because a
built-in pipeline *is* the second pipeline.

P6.6 does not replace any of it. `UnifiedProductionRuntime` satisfies the same
contract, which is why `test_runtime_satisfies_the_p6_0_port_contract` passes.

## The chain

```
product_profile_id
   ↓  ProductCompiler (P6.5 — the only one)
ProductProductionIntent
   ├── NarrativeIntent      P6.1
   ├── PresenterIntent      P6.2
   ├── VisualStyleIntent    P6.3
   ├── VisualIntent         P6.4
   └── RecipeSelectionEvidence   P5.3
   ↓
UnifiedProductionRuntime.submit()
   ├── validate_capabilities()          → BLOCKED_BY_CAPABILITY
   ├── idempotency check (run_id)       → recorded result, delegate not re-entered
   ↓
RuntimeRequest          ← generic fields; NOT a ShotPlan
   ↓  the bound existing runtime
production               ← receipt observed, never synthesised
```

## Run states

`COMPILED · VALIDATED · EXECUTING · PRODUCED · QA_PASSED · QA_FAILED ·
BLOCKED_BY_PROVIDER · BLOCKED_BY_CAPABILITY · FAILED · CANCELLED`

Only `PRODUCED` and `QA_PASSED` are success, and both require an
`ExecutionReceipt(produced=True)`. The dataclass **raises** otherwise, so
`FALSE_SUCCESS=0` is structural.

## Failure classification

| condition | state |
|---|---|
| timeout | `FAILED` / `TIMEOUT:` |
| cancellation | `CANCELLED` |
| CUDA / GPU / OOM / no device | `BLOCKED_BY_PROVIDER` / `GPU_UNAVAILABLE:` |
| 401 / 403 / quota / credentials | `BLOCKED_BY_PROVIDER` / `PROVIDER_ERROR:` |
| anything else | `FAILED` / `RUNTIME_ERROR:` |

No branch in that table produces a success.

## Idempotency, and the bug that shaped it

`run_id` is a content hash of `(product, intent hash, budget, duration, rounds,
locale)` — never a clock, never a UUID.

The first version recorded an *unbound* attempt's `FAILED` result under the run id.
Because the ledger returns the recorded result for a known id, the later legitimate
bound run was permanently blocked by the earlier refusal. Precondition refusals have
no side effects, so they no longer consume identity; a smoke test caught this, not a
designed test.

## What the runtime refuses to be

`ShotPlan` · `MotionPlan` · `ShotPreparation` · `RecipeSelector` · `ShotSelector` ·
`MotionSelector` · `AssetRegistry` · `RenderCommand` — none defined, none imported,
including under an alias.
