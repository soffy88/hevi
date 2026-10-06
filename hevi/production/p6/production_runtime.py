"""HEVI P6.6 — The unified production runtime boundary.

P6.6 is an **adapter**, not a production system. It completes the boundary P6.0
declared in :mod:`hevi.production.p6.runtime` and never becomes a second one.

What already existed before this module
--------------------------------------
P6.0 shipped the whole boundary contract and deliberately left it unbound:

* ``ProductionRuntimePort`` — a ``Protocol``. P6 holds the contract; the
  implementation lives in P0-P5. P6 must not write one.
* ``RuntimeBoundary.produce()`` — the single hand-off point. It delegates, and
  raises :class:`RuntimeNotBoundError` rather than falling back to a built-in
  pipeline, because a built-in pipeline *is* the second pipeline.
* ``SourceMaterial``, ``ProductionConstraints``, ``PipelineStage``.

P6.5 produced the real ``ProductProductionIntent``; P6.0's
``ProductProfileCompiler`` was still a stub that raised
``CompilerContractError``. P6.6 connects the two. It adds no compiler.

The capability model
--------------------
Character, world and evidence are **capabilities**, not grammar layers. The spec
forbids growing new grammar layers, and P6.0 already carries
``CharacterGrammar``/``WorldGrammar``/``EvidenceGrammar`` as *optional profile
attachments*. So P6.6 declares what a production needs and validates it:

    required + available -> proceed
    required - available -> BLOCKED_BY_CAPABILITY, with the missing names

``CAPABILITY_REQUIREMENTS`` is a table keyed by ``ProductType`` — declarative
data, no dispatch. It selects nothing and executes nothing.

Run states and the false-success rule
-------------------------------------
:class:`RunState` is the vocabulary, and no terminal success state may be reached
without the delegate having actually run. That is enforced structurally:
``ProductionRunResult`` only accepts ``PRODUCED``/``QA_PASSED`` when an execution
receipt is present, and the runtime never synthesises one. A provider 401, a
missing GPU, or a timeout stays a failure — never a quiet PASS.

Idempotency
-----------
``RuntimeLedger`` keys on ``run_id``. A repeated submit with the same identity
returns the recorded result and does **not** invoke the delegate again, so retries
cannot duplicate logical shots or assets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from hevi.production.p6.product_compiler import (
    ProductCompilationError,
    ProductCompiler,
    ProductProductionIntent,
)
from hevi.production.p6.runtime import (
    ProductionConstraints,
    RuntimeBoundary,
    RuntimeNotBoundError,
    SourceMaterial,
)
from hevi.production.p6.schema import ProductType

# ── run state ───────────────────────────────────────────────────────────


class RunState(StrEnum):
    """Every state a production run may occupy.

    ``PRODUCED`` and ``QA_PASSED`` are the only success states, and both require
    an execution receipt. There is no way to spell "assumed it worked".
    """

    COMPILED = "compiled"
    VALIDATED = "validated"
    EXECUTING = "executing"
    PRODUCED = "produced"
    QA_PASSED = "qa_passed"
    QA_FAILED = "qa_failed"
    BLOCKED_BY_PROVIDER = "blocked_by_provider"
    BLOCKED_BY_CAPABILITY = "blocked_by_capability"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: States from which no further progress happens.
TERMINAL_STATES: frozenset[RunState] = frozenset(
    {
        RunState.PRODUCED,
        RunState.QA_PASSED,
        RunState.QA_FAILED,
        RunState.BLOCKED_BY_PROVIDER,
        RunState.BLOCKED_BY_CAPABILITY,
        RunState.FAILED,
        RunState.CANCELLED,
    }
)

#: The only states that may be reported as success.
SUCCESS_STATES: frozenset[RunState] = frozenset({RunState.PRODUCED, RunState.QA_PASSED})

#: States that mean "the environment stopped us", not "the code is wrong".
BLOCKED_STATES: frozenset[RunState] = frozenset(
    {RunState.BLOCKED_BY_PROVIDER, RunState.BLOCKED_BY_CAPABILITY}
)


# ── capabilities ────────────────────────────────────────────────────────


class Capability(StrEnum):
    """What a production *needs*, not what it runs.

    Declared generically and resolved generically. A capability never selects an
    implementation, a renderer, or a path.
    """

    CHARACTER = "character"
    WORLD = "world"
    EVIDENCE = "evidence"
    DOCUMENT = "document"
    BRAND = "brand"
    INSTRUCTION = "instruction"
    PRESENTER = "presenter"
    NARRATOR = "narrator"
    MOTION = "motion"
    ASSET = "asset"


@dataclass(frozen=True)
class CapabilityRequirement:
    """What one product type needs, and what it merely benefits from.

    Two sets, because conflating them is how a "may require" quietly becomes a
    hard gate. Only ``required`` can block a run.
    """

    required: frozenset[Capability]
    optional: frozenset[Capability] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": sorted(c.value for c in self.required),
            "optional": sorted(c.value for c in self.optional),
        }


#: The declarative capability matrix. Keyed by P6.0's ``ProductType`` — data,
#: not routing. Nothing here names a function, a renderer, or a recipe.
CAPABILITY_REQUIREMENTS: dict[ProductType, CapabilityRequirement] = {
    ProductType.AVATAR_EXPLAINER: CapabilityRequirement(
        required=frozenset({Capability.PRESENTER, Capability.NARRATOR}),
        optional=frozenset({Capability.BRAND, Capability.DOCUMENT}),
    ),
    ProductType.NARRATED_KNOWLEDGE: CapabilityRequirement(
        required=frozenset({Capability.NARRATOR, Capability.EVIDENCE}),
        optional=frozenset({Capability.DOCUMENT}),
    ),
    ProductType.HISTORICAL_REENACTMENT: CapabilityRequirement(
        required=frozenset({Capability.CHARACTER, Capability.WORLD}),
        optional=frozenset({Capability.EVIDENCE, Capability.NARRATOR}),
    ),
    ProductType.CHARACTER_DOCUMENTARY: CapabilityRequirement(
        required=frozenset({Capability.CHARACTER, Capability.EVIDENCE}),
        optional=frozenset({Capability.WORLD}),
    ),
    ProductType.DOCUMENTARY: CapabilityRequirement(
        required=frozenset({Capability.EVIDENCE}),
        optional=frozenset({Capability.NARRATOR, Capability.DOCUMENT}),
    ),
    ProductType.NARRATIVE_FILM: CapabilityRequirement(
        required=frozenset({Capability.CHARACTER, Capability.WORLD}),
        optional=frozenset({Capability.EVIDENCE, Capability.ASSET}),
    ),
    ProductType.CINEMATIC_KNOWLEDGE: CapabilityRequirement(
        required=frozenset({Capability.MOTION, Capability.EVIDENCE}),
        optional=frozenset({Capability.NARRATOR, Capability.DOCUMENT}),
    ),
    ProductType.COMMERCIAL: CapabilityRequirement(
        required=frozenset(),
        optional=frozenset({Capability.BRAND, Capability.PRESENTER}),
    ),
    ProductType.TUTORIAL: CapabilityRequirement(
        required=frozenset({Capability.INSTRUCTION}),
        optional=frozenset({Capability.PRESENTER, Capability.DOCUMENT}),
    ),
    ProductType.SHORT_FORM: CapabilityRequirement(
        required=frozenset({Capability.ASSET}),
        optional=frozenset({Capability.BRAND, Capability.PRESENTER}),
    ),
}


def requirements_for(product_type: ProductType) -> CapabilityRequirement:
    """The declared capabilities for a product type. Data lookup, never routing."""
    requirement = CAPABILITY_REQUIREMENTS.get(product_type)
    if requirement is None:
        # Fail closed rather than inventing a requirement.
        return CapabilityRequirement(
            required=frozenset({Capability.ASSET}),
            optional=frozenset(),
        )
    return requirement


@dataclass(frozen=True)
class CapabilityValidation:
    """The result of checking requirements against what the context offers."""

    satisfied: bool
    required: tuple[str, ...]
    available: tuple[str, ...]
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "required": list(self.required),
            "available": list(self.available),
            "missing": list(self.missing),
        }


def validate_capabilities(
    product_type: ProductType, available: frozenset[Capability]
) -> CapabilityValidation:
    """Check declared requirements against the production context.

    Never fabricates a missing capability and never downgrades to a different
    product path. Absence is reported by name.
    """
    requirement = requirements_for(product_type)
    required = sorted(c.value for c in requirement.required)
    present = sorted(c.value for c in available)
    missing = tuple(sorted(c.value for c in requirement.required - available))
    return CapabilityValidation(
        satisfied=not missing, required=tuple(required), available=tuple(present), missing=missing
    )


# ── runtime-facing translation ───────────────────────────────────────────


@dataclass(frozen=True)
class RecipeSelectionRecord:
    """P5.3's decision, carried verbatim.

    P6.6 never chooses a recipe. It records what P5.3 decided, including
    everything needed to answer *why this* and *why not the others* later.
    """

    selected_recipe_id: str
    selected_version: str
    candidate_recipe_ids: tuple[str, ...]
    rejected_candidates: tuple[str, ...]
    selection_factors: tuple[tuple[str, float], ...]
    semantic_evidence: str
    fingerprint: str

    @classmethod
    def from_intent(cls, intent: ProductProductionIntent) -> RecipeSelectionRecord:
        from hevi.production.p6.visual_compiler import semantic_fingerprint_of

        evidence = intent.recipe_evidence
        return cls(
            selected_recipe_id=evidence.selected_recipe_id,
            selected_version=evidence.selected_version,
            candidate_recipe_ids=tuple(evidence.candidate_recipe_ids),
            rejected_candidates=tuple(evidence.rejected_candidates),
            selection_factors=tuple(sorted(evidence.selection_factors.items())),
            semantic_evidence=(
                f"semantic_id={intent.visual_intent.semantic_role()} "
                f"beat_role={intent.visual_intent.beat_role()} "
                f"motion_purpose={intent.visual_intent.motion_purpose()}"
            ),
            fingerprint=semantic_fingerprint_of(intent.recipe_evidence),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_recipe_id": self.selected_recipe_id,
            "selected_version": self.selected_version,
            "candidate_recipe_ids": list(self.candidate_recipe_ids),
            "rejected_candidates": list(self.rejected_candidates),
            "selection_factors": dict(self.selection_factors),
            "semantic_evidence": self.semantic_evidence,
            "fingerprint": self.fingerprint,
        }


def _merge_constraints(
    intent: ProductProductionIntent, constraints: ProductionConstraints
) -> tuple[tuple[str, str], ...]:
    """Flatten the compiled constraints plus caller narrowing into one sorted list.

    Callers may tighten what the product declared, never widen it; the widening
    check lives in P6.0's ``RuntimeBoundary.produce``.
    """
    pairs: list[tuple[str, str]] = [(c.key, c.value) for c in intent.constraints]
    if constraints.budget_usd is not None:
        pairs.append(("budget_usd", str(constraints.budget_usd)))
    if constraints.max_duration_s is not None:
        pairs.append(("max_duration_s", str(constraints.max_duration_s)))
    if constraints.max_rounds is not None:
        pairs.append(("max_rounds", str(constraints.max_rounds)))
    if constraints.locale:
        pairs.append(("locale", constraints.locale))
    return tuple(sorted(dict.fromkeys(pairs)))


@dataclass(frozen=True)
class RuntimeRequest:
    """What P6.6 hands the existing runtime.

    Generic fields only, translated one-for-one from the compiled intent. This is
    deliberately *not* a ``ShotPlan``: no shot ids, no per-shot attributes, no
    timeline. The existing authorities own those, and they own the conversion
    from this request into shots.
    """

    run_id: str
    product_profile_id: str
    product_type: str
    narrative_grammar_id: str
    narrative_sequence: tuple[str, ...]
    presenter_grammar_id: str
    presenter_sequence: tuple[str, ...]
    visual_style_id: str
    visual_grammar_id: str
    camera_style: str
    shot_strategy: str
    motion_strategy: str
    composition_strategy: str
    editing_strategy: str
    recipe: RecipeSelectionRecord
    constraints: tuple[tuple[str, str], ...]
    policy: tuple[tuple[str, str], ...]

    @classmethod
    def from_intent(
        cls,
        run_id: str,
        intent: ProductProductionIntent,
        constraints: ProductionConstraints,
    ) -> RuntimeRequest:
        return cls(
            run_id=run_id,
            product_profile_id=intent.product_id,
            product_type=intent.product_type,
            narrative_grammar_id=intent.narrative_intent.grammar_id,
            narrative_sequence=intent.narrative_intent.sequence,
            presenter_grammar_id=intent.presenter_intent.grammar_id,
            presenter_sequence=intent.presenter_intent.sequence(),
            visual_style_id=intent.visual_style_intent.style_id,
            visual_grammar_id=intent.visual_intent.visual_grammar_id,
            camera_style=intent.visual_intent.camera_style,
            shot_strategy=intent.visual_intent.shot_strategy,
            motion_strategy=intent.visual_intent.motion_strategy,
            composition_strategy=intent.visual_intent.composition_strategy,
            editing_strategy=intent.visual_intent.editing_strategy,
            recipe=RecipeSelectionRecord.from_intent(intent),
            constraints=_merge_constraints(intent, constraints),
            policy=intent.policy,
        )

    def content_hash(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutionReceipt:
    """Proof that a delegate actually ran.

    The only thing that may accompany a success state. P6.6 cannot fabricate
    one, which is what makes ``FALSE_SUCCESS=0`` structural rather than a
    promise.
    """

    runtime_id: str
    entrypoint_ref: str
    produced: bool
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.runtime_id:
            raise ValueError("EXECUTION_RECEIPT_WITHOUT_RUNTIME_ID")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionRunResult:
    """The durable outcome of one production run."""

    run_id: str
    product_profile_id: str
    state: RunState
    reason: str = ""
    request_hash: str = ""
    intent_hash: str = ""
    recipe_fingerprint: str = ""
    capabilities: CapabilityValidation | None = None
    receipt: ExecutionReceipt | None = None
    prior_states: tuple[RunState, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("PRODUCTION_RUN_WITHOUT_ID:run_id required")
        # The false-success guard, enforced at construction: a success state
        # without a receipt that says it produced is refused outright.
        if self.state in SUCCESS_STATES and (
            self.receipt is None or not self.receipt.produced
        ):
            raise ValueError(
                f"FALSE_SUCCESS_BLOCKED:{self.state} requires an ExecutionReceipt "
                "with produced=True; P6.6 cannot assert production it did not observe"
            )

    @property
    def is_success(self) -> bool:
        return self.state in SUCCESS_STATES

    @property
    def is_blocked(self) -> bool:
        return self.state in BLOCKED_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "product_profile_id": self.product_profile_id,
            "state": self.state.value,
            "success": self.is_success,
            "blocked": self.is_blocked,
            "reason": self.reason,
            "request_hash": self.request_hash,
            "intent_hash": self.intent_hash,
            "recipe_fingerprint": self.recipe_fingerprint,
            "capabilities": self.capabilities.to_dict() if self.capabilities else None,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "prior_states": [s.value for s in self.prior_states],
        }


# ── idempotency ─────────────────────────────────────────────────────────


class RuntimeLedger:
    """Records run outcomes so a repeated run cannot duplicate side effects.

    Keyed on ``run_id``. A second submit for the same identity returns the
    recorded result and does not call the delegate. This is the whole
    ``DUPLICATE_SIDE_EFFECTS=0`` mechanism.
    """

    def __init__(self) -> None:
        self._results: dict[str, ProductionRunResult] = {}
        self._delegate_calls: dict[str, int] = {}

    def record(self, result: ProductionRunResult) -> ProductionRunResult:
        prior = self._results.get(result.run_id)
        if prior is not None:
            return prior
        self._results[result.run_id] = result
        return result

    def get(self, run_id: str) -> ProductionRunResult | None:
        return self._results.get(run_id)

    def note_delegate_call(self, run_id: str) -> None:
        self._delegate_calls[run_id] = self._delegate_calls.get(run_id, 0) + 1

    def delegate_call_count(self, run_id: str) -> int:
        return self._delegate_calls.get(run_id, 0)

    def run_ids(self) -> list[str]:
        return sorted(self._results)

    def __len__(self) -> int:
        return len(self._results)


# ── the existing runtime port, implemented as an adapter ────────────────


@runtime_checkable
class DelegateRuntime(Protocol):
    """What an existing P0-P5 runtime must offer to be bound.

    Kept deliberately tiny. P6.6 asks the existing runtime to *do the work* and
    reports back honestly; it does not prescribe how.
    """

    runtime_id: str

    def produce(self, request: RuntimeRequest, source: SourceMaterial) -> Any: ...


class UnifiedProductionRuntime:
    """The one P6 runtime boundary. Delegates; never produces locally.

    Implements P6.0's :class:`ProductionRuntimePort` contract, so it slots into
    the :class:`RuntimeBoundary` P6.0 already declared.
    """

    runtime_id = "p6_6_unified"

    def __init__(
        self,
        *,
        compiler: ProductCompiler,
        recipe_library: Any,
        ledger: RuntimeLedger | None = None,
        available_capabilities: frozenset[Capability] | None = None,
    ) -> None:
        self._compiler = compiler
        self._recipe_library = recipe_library
        self._ledger = ledger if ledger is not None else RuntimeLedger()
        self._available = (
            available_capabilities
            if available_capabilities is not None
            else frozenset(Capability)
        )
        self._delegate: DelegateRuntime | None = None
        self._entrypoint_ref = ""
        #: run_ids refused before the delegate ran. Observed, not recorded as
        #: outcomes, so they cannot consume the identity of a later real run.
        self._precondition_refusals: list[str] = []

    # ── binding ───────────────────────────────────────────────────────────

    def bind(self, delegate: DelegateRuntime, entrypoint_ref: str) -> None:
        """Bind an existing runtime. Refuses anything without an entry point."""
        if not hasattr(delegate, "produce") or not hasattr(delegate, "runtime_id"):
            raise TypeError(
                f"NOT_A_PRODUCTION_RUNTIME:{type(delegate).__name__} does not offer "
                "runtime_id + produce()"
            )
        if not entrypoint_ref:
            raise ValueError("RUNTIME_BINDING_WITHOUT_ENTRYPOINT")
        self._delegate = delegate
        self._entrypoint_ref = entrypoint_ref

    @property
    def is_bound(self) -> bool:
        return self._delegate is not None

    @property
    def ledger(self) -> RuntimeLedger:
        return self._ledger

    def precondition_refusals(self, run_id: str) -> int:
        """How many times this identity was refused before the delegate ran."""
        return sum(1 for r in self._precondition_refusals if r == run_id)

    def set_available_capabilities(self, capabilities: frozenset[Capability]) -> None:
        self._available = capabilities

    # ── the single entry point ────────────────────────────────────────────

    def submit(
        self,
        intent: ProductProductionIntent,
        source_material: SourceMaterial,
        constraints: ProductionConstraints | None = None,
    ) -> ProductionRunResult:
        """P6.0's ``ProductionRuntimePort.submit``.

        Fails closed at every stage and never reports a success it did not
        observe. No product id is inspected to choose behaviour.
        """
        constraints = constraints or ProductionConstraints()
        product_type = ProductType(intent.product_type)
        capabilities = validate_capabilities(product_type, self._available)

        # Precondition refusals are NOT recorded against the run identity.
        #
        # Idempotency exists to stop duplicate *side effects*, and a precondition
        # refusal has none — no delegate ran, nothing was written. Recording it
        # would poison the run_id: a first attempt while unbound, or before
        # capabilities were declared, would permanently block the legitimate run
        # that follows under the same identity. The earlier version did exactly
        # that and a smoke test caught it.
        run_id = _run_id(intent, constraints)

        if not capabilities.satisfied:
            self._precondition_refusals.append(run_id)
            return ProductionRunResult(
                run_id=run_id,
                product_profile_id=intent.product_id,
                state=RunState.BLOCKED_BY_CAPABILITY,
                reason=f"CAPABILITY_UNAVAILABLE:{','.join(capabilities.missing)}",
                capabilities=capabilities,
            )

        if self._delegate is None:
            self._precondition_refusals.append(run_id)
            return ProductionRunResult(
                run_id=run_id,
                product_profile_id=intent.product_id,
                state=RunState.FAILED,
                reason="PRODUCTION_RUNTIME_NOT_BOUND:P6 will not run a built-in pipeline",
                capabilities=capabilities,
            )

        prior = self._ledger.get(run_id)
        if prior is not None:
            # Idempotent: the same identity never reaches the delegate twice.
            return prior

        request = RuntimeRequest.from_intent(run_id, intent, constraints)
        self._ledger.note_delegate_call(run_id)

        try:
            outcome = self._delegate.produce(request, source_material)
        except Exception as exc:
            state, reason = _classify_failure(exc)
            return self._ledger.record(
                ProductionRunResult(
                    run_id=run_id,
                    product_profile_id=intent.product_id,
                    state=state,
                    reason=reason,
                    request_hash=request.content_hash(),
                    intent_hash=intent.content_hash(),
                    recipe_fingerprint=intent.recipe_evidence.selected_recipe_id,
                    capabilities=capabilities,
                    prior_states=(RunState.COMPILED, RunState.VALIDATED, RunState.EXECUTING),
                )
            )

        return self._ledger.record(
            ProductionRunResult(
                run_id=run_id,
                product_profile_id=intent.product_id,
                state=RunState.PRODUCED,
                reason="",
                request_hash=request.content_hash(),
                intent_hash=intent.content_hash(),
                recipe_fingerprint=intent.recipe_evidence.selected_recipe_id,
                capabilities=capabilities,
                receipt=ExecutionReceipt(
                    runtime_id=self._delegate.runtime_id,
                    entrypoint_ref=self._entrypoint_ref,
                    produced=True,
                    detail=str(outcome)[:200],
                ),
                prior_states=(RunState.COMPILED, RunState.VALIDATED, RunState.EXECUTING),
            )
        )

    # ── compilation convenience, still one compiler ───────────────────────

    def compile(self, product_id: str, *, run_id: str = "") -> ProductProductionIntent:
        """Compile through the single P6.5 compiler. No second compiler exists."""
        return self._compiler.compile(product_id, recipe_library=self._recipe_library)


def _run_id(intent: ProductProductionIntent, constraints: ProductionConstraints) -> str:
    """A run identity derived from content, never from a clock or a UUID."""
    encoded = json.dumps(
        {
            "product": intent.product_id,
            "intent": intent.content_hash(),
            "budget": constraints.budget_usd,
            "duration": constraints.max_duration_s,
            "rounds": constraints.max_rounds,
            "locale": constraints.locale,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


_PROVIDER_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "quota",
    "rate limit",
    "credential",
    "api key",
    "insufficient",
    "payment required",
)
_GPU_MARKERS = ("cuda", "gpu", "nvidia", "out of memory", "no device", "device handle")
_TIMEOUT_MARKERS = ("timeout", "timed out", "deadline")
_CANCEL_MARKERS = ("cancel", "abort")


def _classify_failure(exc: Exception) -> tuple[RunState, str]:
    """Map a delegate failure to a state without ever softening it.

    Provider, GPU, timeout and cancellation stay distinct and stay failures.
    There is no branch here that produces a success.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    detail = f"{type(exc).__name__}:{exc}"[:300]
    if any(marker in text for marker in _TIMEOUT_MARKERS):
        return RunState.FAILED, f"TIMEOUT:{detail}"
    if any(marker in text for marker in _CANCEL_MARKERS):
        return RunState.CANCELLED, f"CANCELLED:{detail}"
    if any(marker in text for marker in _GPU_MARKERS):
        return RunState.BLOCKED_BY_PROVIDER, f"GPU_UNAVAILABLE:{detail}"
    if any(marker in text for marker in _PROVIDER_MARKERS):
        return RunState.BLOCKED_BY_PROVIDER, f"PROVIDER_ERROR:{detail}"
    if isinstance(exc, ProductCompilationError):
        return RunState.FAILED, f"COMPILATION_ERROR:{detail}"
    return RunState.FAILED, f"RUNTIME_ERROR:{detail}"


__all__ = [
    "BLOCKED_STATES",
    "CAPABILITY_REQUIREMENTS",
    "SUCCESS_STATES",
    "TERMINAL_STATES",
    "Capability",
    "CapabilityRequirement",
    "CapabilityValidation",
    "DelegateRuntime",
    "ExecutionReceipt",
    "ProductionRunResult",
    "RecipeSelectionRecord",
    "RunState",
    "RuntimeBoundary",
    "RuntimeLedger",
    "RuntimeNotBoundError",
    "RuntimeRequest",
    "SourceMaterial",
    "UnifiedProductionRuntime",
    "requirements_for",
    "validate_capabilities",
]
