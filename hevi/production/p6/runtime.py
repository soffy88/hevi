"""HEVI P6 — runtime boundary (P6.0 architecture).

P6 declares *one* unified entry point and delegates. It does not implement
production.

    produce(product_profile, source_material, production_constraints)
        -> resolve_product_profile()
        -> compile_grammar()            (P6.1+; raises in P6.0)
        -> validate_constraints()
        -> build_narrative()
        -> build_semantic_plan()
        -> invoke_existing_runtime()    <-- P0-P5 own this
        -> P5 editorial / render / delivery

The delegation target is not P6's to choose. HEVI has two existing production
entry points, and P6 uses them rather than adding a third:

* ``hevi.production.p2_pipeline.run_p2_production`` — the canonical P0->P1->P2
  chain.
* ``hevi.tasks.task_service.TaskService.run_task`` — the API/task path.

P6.0 therefore ships :class:`ProductionRuntimePort`, a protocol describing what
P6 needs from a runtime, plus a registry that records which existing runtime a
deployment has bound. It ships **no** implementation of that port, because any
implementation inside P6 would be the second pipeline that
``NO_SECOND_PIPELINE`` forbids.

The pipeline steps named in ``PIPELINE_STAGES`` are *declarations of hand-off
points*, in the order the existing runtime performs them. P6 does not
implement, reorder, or skip them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from hevi.production.p6.compiler import CompiledProductIntent, ProductProfileCompiler
from hevi.production.p6.schema import ProductProfile


class PipelineStage(StrEnum):
    """Declared hand-off points into the existing runtime.

    These name what already happens. They are not P6 stages to execute.
    """

    RESOLVE_PROFILE = "resolve_product_profile"
    COMPILE_GRAMMAR = "compile_grammar"
    VALIDATE_CONSTRAINTS = "validate_constraints"
    BUILD_NARRATIVE = "build_narrative"
    BUILD_SEMANTIC_PLAN = "build_semantic_plan"
    INVOKE_EXISTING_RUNTIME = "invoke_existing_runtime"
    EDITORIAL_RENDER_DELIVERY = "editorial_render_delivery"


#: Canonical order. P6 asserts this list is stable and complete; it does not walk it.
PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.RESOLVE_PROFILE,
    PipelineStage.COMPILE_GRAMMAR,
    PipelineStage.VALIDATE_CONSTRAINTS,
    PipelineStage.BUILD_NARRATIVE,
    PipelineStage.BUILD_SEMANTIC_PLAN,
    PipelineStage.INVOKE_EXISTING_RUNTIME,
    PipelineStage.EDITORIAL_RENDER_DELIVERY,
)


class RuntimeNotBoundError(RuntimeError):
    """Raised when P6 is asked to produce before a runtime has been bound.

    Fail-closed. P6 will not fall back to a built-in pipeline, because the
    built-in pipeline is precisely the second pipeline the architecture forbids.
    """


@dataclass(frozen=True)
class SourceMaterial:
    """Declared input material. A reference, not a loaded asset.

    ``material_refs`` point at assets owned by the existing asset authority.
    P6 never fetches, stores, or validates them; it states what the product
    expects to be given.
    """

    material_refs: tuple[str, ...] = ()
    narration_ref: str = ""
    transcript_ref: str = ""
    source_uri: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not (self.material_refs or self.narration_ref or self.source_uri):
            raise ValueError(
                "EMPTY_SOURCE_MATERIAL:at least one material reference required"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_refs": list(self.material_refs),
            "narration_ref": self.narration_ref,
            "transcript_ref": self.transcript_ref,
            "source_uri": self.source_uri,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ProductionConstraints:
    """Caller-supplied constraints for one production.

    These narrow an already-declared product. They cannot widen it past what
    the ``ProductProfile`` permits, and they never name a renderer.
    """

    budget_usd: float | None = None
    max_duration_s: float | None = None
    max_rounds: int | None = None
    locale: str = ""
    extra: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.budget_usd is not None and self.budget_usd < 0:
            raise ValueError(f"NEGATIVE_BUDGET:{self.budget_usd}")
        if self.max_duration_s is not None and self.max_duration_s <= 0:
            raise ValueError(f"INVALID_MAX_DURATION:{self.max_duration_s}")
        if self.max_rounds is not None and self.max_rounds < 1:
            raise ValueError(f"INVALID_MAX_ROUNDS:{self.max_rounds}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class ProductionRuntimePort(Protocol):
    """What P6 needs from the existing production runtime.

    An implementation of this protocol lives in P0-P5, not in P6. P6 holds the
    protocol so the boundary is explicit and checkable.
    """

    runtime_id: str

    def submit(
        self,
        intent: CompiledProductIntent,
        source_material: SourceMaterial,
        constraints: ProductionConstraints,
    ) -> Any:
        """Hand compiled intent to the existing runtime. Returns its result."""
        ...


@dataclass
class RuntimeBinding:
    """Records which existing runtime P6 has been pointed at.

    Declaration only: P6.0 binds nothing. Populating this is a deployment
    decision, and it must name a runtime that already exists.
    """

    runtime_id: str
    entrypoint_ref: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.runtime_id:
            raise ValueError("RUNTIME_BINDING_WITHOUT_ID:runtime_id required")
        if not self.entrypoint_ref:
            raise ValueError(
                "RUNTIME_BINDING_WITHOUT_ENTRYPOINT:entrypoint_ref must name the "
                "existing entry point being delegated to"
            )


class RuntimeBoundary:
    """The single P6 hand-off point to the existing runtime.

    Constructing this with no binding is legal — P6.0 ships unbound. Calling
    :meth:`produce` while unbound raises :class:`RuntimeNotBoundError`.
    """

    def __init__(
        self,
        *,
        compiler: ProductProfileCompiler,
        binding: RuntimeBinding | None = None,
    ) -> None:
        self._compiler = compiler
        self._binding = binding
        self._runtime: ProductionRuntimePort | None = None

    @property
    def compiler(self) -> ProductProfileCompiler:
        return self._compiler

    @property
    def binding(self) -> RuntimeBinding | None:
        return self._binding

    @property
    def is_bound(self) -> bool:
        return self._runtime is not None

    def bind(self, runtime: ProductionRuntimePort, binding: RuntimeBinding) -> None:
        """Bind an existing runtime. Refuses anything not implementing the port."""
        if not isinstance(runtime, ProductionRuntimePort):
            raise TypeError(
                f"NOT_A_PRODUCTION_RUNTIME:{type(runtime).__name__} does not "
                "implement ProductionRuntimePort"
            )
        if not binding.entrypoint_ref:
            raise ValueError("RUNTIME_BINDING_WITHOUT_ENTRYPOINT")
        self._runtime = runtime
        self._binding = binding

    def produce(
        self,
        product_profile: ProductProfile,
        source_material: SourceMaterial,
        production_constraints: ProductionConstraints | None = None,
    ) -> Any:
        """The unified P6 entry point. Delegates; never produces locally.

        P6.0 stops at the compiler, which itself raises
        :class:`~hevi.production.p6.compiler.CompilerContractError`. This is
        deliberate: the boundary is proven fail-closed before any grammar work
        exists.
        """
        if not isinstance(product_profile, ProductProfile):
            raise TypeError(
                f"NOT_A_PRODUCT_PROFILE:{type(product_profile).__name__}"
            )
        if not isinstance(source_material, SourceMaterial):
            raise TypeError(
                f"NOT_SOURCE_MATERIAL:{type(source_material).__name__}"
            )
        constraints = production_constraints or ProductionConstraints()

        # Stage: resolve_product_profile — validated by the compiler.
        intent = self._compiler.compile_profile(product_profile)

        # Stage: validate_constraints — declared narrowing only. A caller may
        # tighten a product's declared bounds, never widen them.
        policy = product_profile.duration_policy
        if (
            constraints.max_duration_s is not None
            and policy is not None
            and constraints.max_duration_s > policy.max_s
        ):
            raise ValueError(
                f"CONSTRAINT_EXCEEDS_PRODUCT_DECLARATION:"
                f"{constraints.max_duration_s} > {policy.max_s}"
            )

        # Stage: invoke_existing_runtime — refused while unbound.
        if self._runtime is None:
            raise RuntimeNotBoundError(
                "PRODUCTION_RUNTIME_NOT_BOUND:P6 will not run a built-in pipeline; "
                f"bind an existing runtime (declared: {self._binding}) first"
            )
        return self._runtime.submit(intent, source_material, constraints)

    def to_dict(self) -> dict[str, Any]:
        binding: dict[str, Any] | None = None
        if self._binding is not None:
            binding = {
                "runtime_id": self._binding.runtime_id,
                "entrypoint_ref": self._binding.entrypoint_ref,
                "notes": self._binding.notes,
            }
        return {
            "compiler_id": getattr(
                self._compiler, "compiler_id", type(self._compiler).__name__
            ),
            "is_bound": self.is_bound,
            "binding": binding,
            "declared_stages": [s.value for s in PIPELINE_STAGES],
        }


__all__ = [
    "PIPELINE_STAGES",
    "PipelineStage",
    "ProductionConstraints",
    "ProductionRuntimePort",
    "RuntimeBinding",
    "RuntimeBoundary",
    "RuntimeNotBoundError",
    "SourceMaterial",
]
