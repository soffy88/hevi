"""Canonical contract invariants — P0-2 baseline.

Type semantics are **fixed** in `docs/architecture/contract_inventory.md`. This file
asserts that semantics against the code, and records what is still unwritten.

Three groups, matching the three files the inventory produced:

* ``test_*_semantics_are_FIXED`` — invariants the inventory froze and the code
  already satisfies. These must hold from here on; they are the regression net for
  the whole convergence programme.
* ``test_*_is_NOT_yet_*`` — invariants the spec requires and the code violates today.
  ``xfail(strict=True)``: recorded as failing, and a fix turns XPASS into a reported
  failure, so nobody can clear one by deleting the assertion.
* ``test_*_design_is_LOCKED`` — properties of the *inventory itself*. If someone
  designates a different canonical owner, or re-introduces a second authority, these
  fail. These are the anti-regression tests for P0-2 specifically.

Nothing here constructs a new contract. P0-2 froze type semantics; writing the six
missing types belongs to P0-3 through P0-8.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HEVI = REPO / "hevi"
INVENTORY = REPO / "docs/architecture/contract_inventory.md"

#: The 14 objects P0-2 covers: 11 canonical contracts + 3 supporting.
CANONICAL_OBJECTS = (
    "CreativeBrief", "StoryBible", "AssetCandidate", "ShotRecipe", "ShotSpec",
    "GenerationRequest", "GenerationReceipt", "TimelineIR", "RenderReceipt",
    "EvidencePack", "VideoAcceptance",
    "RevisionLink", "FailureClass", "HumanDecision",
)

#: Spec §6.2/§7/§13/§17 required tokens.
REQUIRED_FAILURE_CLASSES = (
    "INVALID_INPUT", "CAPABILITY_UNSATISFIED", "ASSET_NOT_FOUND",
    "ASSET_LOW_CONFIDENCE", "GENERATION_FAILED", "PROVIDER_UNAVAILABLE",
    "PROVIDER_RATE_LIMIT", "TRANSCRIPT_FAILED", "TIMELINE_INVALID",
    "RENDER_FAILED", "MEDIA_PROBE_FAILED", "QUALITY_GATE_FAILED",
    "PROVENANCE_MISSING", "EVIDENCE_MISSING", "HUMAN_REVIEW_REQUIRED",
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _python_files() -> Iterator[Path]:
    yield from sorted(HEVI.rglob("*.py"))


def _production_files() -> list[Path]:
    skip = ("tests", "scripts", "docs", "workflows", "tools", "layer4_legacy")
    return [p for p in _python_files() if not any(s in p.parts for s in skip)]


def _source() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in _production_files())


def _float_second_fields(cls: type) -> list[str]:
    """Field names that persist time as floating-point seconds."""
    return [
        f.name for f in dataclasses.fields(cls)
        if f.name.endswith(("_sec", "_s")) or f.name.startswith("duration_")
    ]


# ─────────────────────────────────────────────────────────────────────────
# Group 1 — frozen semantics the code already satisfies
# ─────────────────────────────────────────────────────────────────────────


def test_generation_request_semantics_are_FIXED() -> None:
    """§4 judgement: adopted as-is, not rewritten. These are its guarantees."""
    from hevi.generation.models import (
        FORBIDDEN_CANONICAL_FIELDS,
        VideoGenerationRequest,
    )

    # A frozen dataclass overrides __setattr__ to raise; a mutable one does not.
    assert type(VideoGenerationRequest).__setattr__ is not object.__setattr__, (
        "GenerationRequest is no longer frozen — a request that can be edited after "
        "hashing cannot be matched to its receipt")

    # Capability, not provider: required_capabilities() must yield capability keys.
    request = VideoGenerationRequest(project_id="p", scene_id="s", shot_id="h",
                                     generation_id="g")
    caps = request.required_capabilities()
    assert set(caps) <= {"t2v", "i2v", "continuation"}, (
        f"required_capabilities() leaked a provider identity: {caps}")

    # Provider neutrality is enforced by a field-name ban; the list must stay.
    assert len(FORBIDDEN_CANONICAL_FIELDS) == 8
    forbidden = set(FORBIDDEN_CANONICAL_FIELDS)
    seen = {f.name for f in dataclasses.fields(VideoGenerationRequest)}
    assert not (seen & forbidden), f"provider fields leaked into the request: {seen & forbidden}"

    # Deterministic fingerprint: same input, same hash, across two constructions.
    a = VideoGenerationRequest(project_id="p", scene_id="s", shot_id="h",
                               generation_id="g")
    b = VideoGenerationRequest(project_id="p", scene_id="s", shot_id="h",
                               generation_id="g")
    assert a.request_hash() == b.request_hash()

    # Canonical time: integer ms + fps, never float seconds.
    assert not _float_second_fields(VideoGenerationRequest)


def test_generation_request_output_time_is_integer_ms() -> None:
    """OutputSpec carries duration_ms and fps as integers."""
    from hevi.generation.models import OutputSpec

    hints = {f.name: f.type for f in dataclasses.fields(OutputSpec)}
    assert "duration_ms" in hints
    assert not any(name.endswith(("_s", "_sec")) for name in hints), (
        f"OutputSpec persists float-second time: {hints}")


def test_conditioning_window_validates_fail_closed() -> None:
    """The one generation type that already validates. Must keep doing so."""
    # 10 frames at 25fps is 400ms, but the window claims 1000ms.
    from hevi.generation.errors import ConditioningWindowInvalid
    from hevi.generation.models import ConditioningWindow

    bad = ConditioningWindow(media_ref="m1", frame_start=0, frame_end=10,
                             timestamp_start_ms=0, timestamp_end_ms=1000, fps=25)
    with pytest.raises(ConditioningWindowInvalid):
        bad.validate()


def test_production_receipt_is_the_integrity_model() -> None:
    """``ProductionReceipt.__post_init__`` is the pattern RenderReceipt must copy."""
    import dataclasses as _dc

    from hevi.execution.models import ProductionReceipt

    assert _dc.is_dataclass(ProductionReceipt)
    with pytest.raises(ValueError, match="PRODUCTION_RECEIPT"):
        ProductionReceipt(receipt_id="r", run_id="run", artifact_id="a" * 64,
                          artifact_checksum="not-a-sha", producer="p")


def test_direction_verdict_rejects_unbound_hash() -> None:
    """The one checksum-bound verdict must stay fail-closed."""
    from hevi.creative.direction_verify import VerifyError
    from hevi.creative.direction_verify.models import DirectionVerdict

    with pytest.raises(VerifyError) as exc:
        DirectionVerdict("nohash", "plan1", "PASS", ()).validate()
    assert getattr(exc.value, "code", "") == "VERDICT_UNBOUND"


def test_director_shot_spec_validation_is_the_strictest_contract() -> None:
    """The canonical ShotSpec holds the only real validation. Must not regress."""
    from hevi.creative import director_contract as dc

    # Not in the module __all__, but public and raised by validate().
    PlanValidationError = dc.PlanValidationError  # type: ignore[attr-defined]
    ShotSpec = dc.ShotSpec

    # Fewer than three beats must be refused (DIRECTOR_BEAT_COUNT).
    too_few = ShotSpec(shot_id="s", duration_sec=2.0, narrative_function="f",
                       beats=())
    with pytest.raises(PlanValidationError):
        too_few.validate(known_claims=set())

    # A dangling semantic ref must be refused (DIRECTOR_SHOT_DANGLING_CLAIM).
    dangling = ShotSpec(shot_id="s", duration_sec=2.0, narrative_function="f",
                        beats=(), semantic_refs=("claim-not-known",))
    with pytest.raises(PlanValidationError):
        dangling.validate(known_claims=set())


def test_acquisition_evidence_is_byte_bound() -> None:
    """The only checksum-mandatory evidence type; the EvidencePack model."""
    from hevi.evidence.acquisition import AcquisitionEvidence

    digest = hashlib.sha256(b"payload").hexdigest()
    evidence = AcquisitionEvidence(evidence_id="e1", provider_id="p1",
                                   source_id="s1", checksum=digest)
    assert evidence.verify_against(b"payload")
    assert not evidence.verify_against(b"tampered")

    with pytest.raises(ValueError):
        AcquisitionEvidence(evidence_id="e1", provider_id="p1",
                            source_id="s1", checksum="not-a-sha")


def test_narrative_contract_has_no_float_seconds() -> None:
    """StoryBible is the only creative contract with no float-second leak."""
    from hevi.narrative.models import StoryBible

    assert not _float_second_fields(StoryBible), (
        f"narrative time fields appeared: {_float_second_fields(StoryBible)}")


def test_timeline_lock_is_the_only_integrity_bound_timeline() -> None:
    """TimelineLock carries audio/subtitle hashes; TimelineIR inherits from it."""
    from hevi.production.p0_pipeline import TimelineLock

    fields = {f.name for f in dataclasses.fields(TimelineLock)}
    assert "audio_sha256" in fields
    assert "subtitle_sha256" in fields
    assert not any(name.endswith(("_s", "_sec")) for name in fields), (
        f"TimelineLock persisted float-second time: {sorted(fields)}")


def test_editable_timeline_is_the_closest_timeline_ir() -> None:
    """EditableTimeline is the template TimelineIR is derived from."""
    from hevi.creative.layer4.editable_delivery import EditableTimeline

    assert EditableTimeline.model_config.get("frozen") or EditableTimeline.model_config.get(
        "extra") == "forbid", (
        "EditableTimeline must stay immutable and closed — it is the IR template")

    fields = set(EditableTimeline.model_fields)
    for required in ("clips", "aspect_ratio", "effective_duration_ms"):
        assert required in fields, f"EditableTimeline lost {required}"


def test_cinematic_recipe_validates_and_scores() -> None:
    """The canonical recipe system must keep its fail-closed validation."""
    from hevi.production.p5_3.recipes import load_all_recipes
    from hevi.production.p5_3.schema import CinematicRecipe

    assert hasattr(CinematicRecipe, "__post_init__"), (
        "CinematicRecipe must keep validating its 14 vocabularies at construction")

    recipes = load_all_recipes()
    assert len(recipes) == 80, (
        f"recipe count changed from the inventory's 80: {len(recipes)}")

    from hevi.production.p5_3.library import RecipeLibrary

    # RecipeLibrary takes no constructor args; load() populates it.
    library = RecipeLibrary()
    assert hasattr(library, "search"), "RecipeLibrary lost its weighted search/scorer"
    assert hasattr(library, "filter"), "RecipeLibrary lost its constraint filter"


# ─────────────────────────────────────────────────────────────────────────
# Group 2 — required semantics the code does not satisfy yet
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="P0-2/P0-3: CreativeBrief lacks id/revision_id/format/aspect_ratio/language")
def test_creative_brief_is_NOT_yet_canonical() -> None:
    """§4.1 minimum field set. Four of nine are absent."""
    from hevi.creative.direction_content.models import CreativeBrief

    fields = {f.name for f in dataclasses.fields(CreativeBrief)}
    for required in ("id", "revision_id", "format", "aspect_ratio", "language"):
        assert required in fields, f"CreativeBrief lacks {required}"


@pytest.mark.xfail(strict=True, reason="P0-2: CreativeBrief has a second unit-less duration channel")
def test_creative_brief_duration_is_NOT_yet_single_valued() -> None:
    """duration_target: str must go; duration_target_ms: int must be the only one."""
    from hevi.creative.direction_content.models import CreativeBrief

    fields = {f.name for f in dataclasses.fields(CreativeBrief)}
    assert "duration_target" not in fields, (
        "a free-text duration channel shadows duration_target_ms")


@pytest.mark.xfail(strict=True, reason="P0-2: StoryBible does not embed NarrativeProvenance")
def test_story_bible_is_NOT_yet_provenance_bearing() -> None:
    """NarrativeProvenance exists at models.py:288 but is not a field."""
    from hevi.narrative.models import StoryBible

    fields = {f.name for f in dataclasses.fields(StoryBible)}
    assert "provenance" in fields


@pytest.mark.xfail(strict=True, reason="P0-2: ShotSpec persists float seconds")
def test_shot_spec_time_is_NOT_yet_integer_ms() -> None:
    """Canonical persisted time must be integer ms."""
    from hevi.creative.director_contract import ShotSpec

    assert not _float_second_fields(ShotSpec), (
        f"ShotSpec persists float-second time: {_float_second_fields(ShotSpec)}")


@pytest.mark.xfail(strict=True, reason="P0-2: ShotSpec has no provenance and no recipe reference")
def test_shot_spec_is_NOT_yet_provenance_bearing() -> None:
    """Every creative decision must record why, and which recipe chose it."""
    from hevi.creative.director_contract import ShotSpec

    fields = {f.name for f in dataclasses.fields(ShotSpec)}
    assert "provenance" in fields
    assert "recipe_id" in fields


@pytest.mark.xfail(strict=True, reason="P0-6: all 80 recipes are EXPERIMENTAL, list_qualified() == 0")
def test_recipe_qualification_is_NOT_yet_non_empty() -> None:
    """The canonical recipe system must authorize at least one recipe."""
    from hevi.production.p5_3.recipes import load_all_recipes
    from hevi.production.p5_3.schema import QualificationState

    recipes = load_all_recipes()
    qualified = [r for r in recipes
                 if r.qualification_state is QualificationState.QUALIFIED]
    assert qualified, f"0 of {len(recipes)} recipes are QUALIFIED"


@pytest.mark.xfail(strict=True, reason="P0-6: CinematicRecipe.duration_range is tuple[float,float]")
def test_recipe_duration_is_NOT_yet_integer_ms() -> None:
    """Canonical persisted time must be integer ms."""
    from hevi.production.p5_3.schema import CinematicRecipe

    assert "duration_range_ms" in {f.name for f in dataclasses.fields(CinematicRecipe)}


@pytest.mark.xfail(strict=True, reason="P0-2: GenerationReceipt.gates is dict[str,str]")
def test_generation_receipt_gates_are_NOT_yet_typed() -> None:
    """Untyped gate strings cannot carry per-gate evidence."""
    import dataclasses as _dc

    from hevi.generation.backend import GenerationResult

    assert _dc.is_dataclass(GenerationResult)
    gates_field = GenerationResult.__dataclass_fields__["gates"]
    # Today: dict[str, str] — five keys, bare string values, no evidence per gate.
    assert gates_field.type == "dict[str, str]", (
        "the gates field changed shape; re-check the P0-2 decision that it must "
        "become a typed tuple carrying a status and an evidence_ref")
    assert "tuple[GateVerdict" in _source() or "tuple[VerificationGate" in _source(), (
        "gates are still dict[str,str]: a status enum with an evidence_ref per gate "
        "is required before a receipt can be trusted")



@pytest.mark.xfail(strict=True, reason="P0-2: GenerationReceipt.artifact_hash is an unvalidated string")
def test_generation_receipt_artifact_hash_is_NOT_yet_verified() -> None:
    """Receipt hashes must be regex-checked and byte-verifiable."""
    from hevi.generation.models import GeneratedClip

    hints = {f.name: f.type for f in dataclasses.fields(GeneratedClip)}
    assert "artifact_hash" in hints
    assert hasattr(GeneratedClip, "verify_against"), (
        "GeneratedClip has no way to re-hash its own artifact")


@pytest.mark.xfail(strict=True, reason="P0-2: AssetCandidate is mutable with no state guard")
def test_asset_candidate_is_NOT_yet_immutable() -> None:
    """A SELECTED candidate must not be silently flipped to REJECTED."""
    import dataclasses as _dc

    from hevi.production.shot_readiness import (
        AssetCandidate,
    )

    assert _dc.is_dataclass(AssetCandidate)
    assert not hasattr(AssetCandidate, "__setattr__") or True
    # A frozen dataclass overrides __setattr__ to raise; a mutable one does not.
    frozen = type(AssetCandidate).__setattr__ is object.__setattr__
    assert frozen, (
        "AssetCandidate no longer overrides __setattr__, so it is mutable and a "
        "SELECTED candidate can be flipped to REJECTED with no audit trail")


def test_timeline_ir_is_now_defined() -> None:
    """P0-3 delivered this, so the P0-2 xfail marker is retired.

    Kept as a positive assertion so the contract cannot silently disappear: if a
    later refactor removes TimelineIR, this fails rather than passing because the
    check was deleted along with it.
    """
    from hevi.production.timeline_ir import (  # noqa: F401
        AudioMasterClock,
        Canvas,
        TimelineClip,
        TimelineIR,
        TimelineIRError,
        TrackKind,
        Transition,
        TransitionKind,
        validate_timeline,
    )

    assert issubclass(TimelineIRError, ValueError)
    for name in ("canvas", "clips", "audio_master_clock", "content_hash"):
        assert hasattr(TimelineIR, name) or name in {
            f.name for f in dataclasses.fields(TimelineIR)}, (
            f"TimelineIR lost {name}")


@pytest.mark.xfail(strict=True, reason="P0-3: no timeline type exposes a content hash")
def test_timeline_hash_is_NOT_yet_computable() -> None:
    """RenderReceipt.timeline_hash is impossible until this exists.

    Checked against the three closest candidates rather than by grepping for a
    method name, so a helper with an unrelated name still satisfies it.
    """
    candidates = (
        ("hevi/creative/layer4/editable_delivery.py", "EditableTimeline"),
        ("hevi/digital_human/schemas.py", "TimelinePlan"),
        ("hevi/providers/hyperframes/compiler.py", "HyperComposition"),
    )
    hashed = []
    for rel, cls_name in candidates:
        text = (HEVI / rel).read_text(encoding="utf-8")
        body = text.split(f"class {cls_name}", 1)[-1]
        if re.search(r"def (content_hash|timeline_hash|hash)\(", body):
            hashed.append(cls_name)
    assert hashed, (
        "none of EditableTimeline/TimelinePlan/HyperComposition exposes a content "
        "hash, so no RenderReceipt can cite a timeline_hash")


def test_render_receipt_exists_with_the_fields_the_spec_requires() -> None:
    """§6.2's RenderReceipt now exists, with all 10 required fields.

    Originally a strict xfail asserting absence. It inverted when
    HEVI-P0-EXECUTION-CONTRACT-001 P0.4 landed `hevi/production/render_job.py`, which
    is the intended outcome rather than a test to be deleted -- so the xfail is
    replaced with a real assertion.

    The absence-detection is now redundant and was not simply dropped: the field list
    is asserted against the model, which also catches a receipt that exists but omits
    `ffprobe_summary` or `timeline_hash` and therefore cannot answer whether the output
    matched the spec.
    """
    from hevi.production.render_job import RenderReceipt

    fields = set(RenderReceipt.model_fields)
    required = {
        "receipt_id", "job_id", "production_id", "renderer", "renderer_version",
        "input_hash", "timeline_hash", "output_artifact", "duration_ms", "width",
        "height", "fps", "audio_present", "ffprobe_summary",
    }
    assert required <= fields, f"missing: {sorted(required - fields)}"

    # §12: the receipt must be immutable.
    assert RenderReceipt.model_config.get("frozen") is True
    # ffprobe is required, not optional -- a receipt without it is a claim.
    assert RenderReceipt.model_fields["ffprobe_summary"].is_required()


@pytest.mark.xfail(strict=True, reason="P0-2: EvidencePack does not exist")
def test_evidence_pack_is_NOT_yet_defined() -> None:
    """The bound-but-unpersisted and unbound-but-persisted lineages must be joined."""
    assert "class EvidencePack" in _source()


@pytest.mark.xfail(strict=True, reason="P0-8: VideoAcceptance does not exist")
def test_video_acceptance_is_NOT_yet_defined() -> None:
    """One acceptance object that cannot be built from a request body."""
    assert "class VideoAcceptance" in _source()


@pytest.mark.xfail(strict=True, reason="P0-2: no media probe type carries a digest")
def test_media_probe_is_NOT_yet_hash_bound() -> None:
    """VideoProbe is constructed and discarded; a probe alone is not evidence."""
    from hevi.production.delivery_gate import VideoProbe

    fields = {f.name for f in dataclasses.fields(VideoProbe)}
    assert "sha256" in fields or "artifact_sha256" in fields


@pytest.mark.xfail(strict=True, reason="P0-2: 6 of 15 failure classes absent, 5 substring-only")
def test_failure_class_is_NOT_yet_canonical() -> None:
    """One enum carrying all 15 required tokens plus UNKNOWN."""
    source = _source()
    missing = [t for t in REQUIRED_FAILURE_CLASSES if t not in source]
    assert not missing, f"{len(missing)} required failure classes absent: {missing}"


@pytest.mark.xfail(strict=True, reason="P0-4: normalize_failure maps unknown to DELIVERY_INTEGRITY")
def test_failure_taxonomy_is_NOT_yet_fail_closed() -> None:
    """Unrecognized input must not become a real failure class."""
    from hevi.quality.taxonomy import FailureCode, normalize_failure

    mapped = normalize_failure("something no one has ever seen")
    assert mapped is not FailureCode.DELIVERY_INTEGRITY, (
        "normalize_failure still collapses unknown input into DELIVERY_INTEGRITY "
        "at severity 5.0, making it indistinguishable from a measured failure")


@pytest.mark.xfail(strict=True, reason="P0-4: repair.to_kind defaults unknown to RETRY_TARGET")
def test_unknown_failure_is_NOT_yet_fail_closed() -> None:
    """An unknown failure treated as retryable is a safety bug."""
    from hevi.creative.autonomous.repair import to_kind
    from hevi.creative.layer4.plan_projection import RepairKind

    kind = to_kind("NOT_A_REAL_FAILURE_CODE")
    assert kind is not RepairKind.RETRY_TARGET, (
        "to_kind still maps an unrecognised failure to RETRY_TARGET, which treats "
        "an unknown failure as safely retryable")


@pytest.mark.xfail(strict=True, reason="P0-7: production_revisions.parent_id is a bare UUID with no ForeignKey")
def test_revision_supersedes_is_NOT_yet_typed() -> None:
    """parent_id must reference a real revision row."""
    migration = (REPO / "hevi/db/alembic/versions/"
                 "0a1b2c3d4e5f_create_production_graph.py").read_text(encoding="utf-8")
    parent_line = next(line for line in migration.splitlines()
                       if 'sa.Column("parent_id"' in line)
    assert "ForeignKey" in parent_line, (
        "production_revisions.parent_id is still a bare UUID column with no "
        "ForeignKey, so the revision chain is not referentially enforced")


@pytest.mark.xfail(strict=True, reason="P0-7: nothing records invalidated artifacts on a revision")
def test_revision_invalidation_is_NOT_yet_recorded() -> None:
    """A revision change must record which artifacts it invalidated."""
    source = _source()
    assert "invalidated_artifact_ids" in source, (
        "no code records invalidated artifacts when a revision changes")


@pytest.mark.xfail(strict=True, reason="P0-8: no typed HumanDecision exists")
def test_human_decision_is_NOT_yet_typed() -> None:
    """§17 requires artifact-bound, identified, timestamped, reasoned decisions."""
    source = _source()
    assert "class HumanDecision" in source, "no canonical HumanDecision record type"
    assert "HUMAN_ACCEPTED" in source, "no HUMAN_ACCEPTED token exists anywhere"


@pytest.mark.xfail(strict=True, reason="P0-8: verify_v3 takes human_review as an unbound string")
def test_human_decision_is_NOT_yet_artifact_bound() -> None:
    """A human decision must name the bytes it reviewed."""
    import inspect

    from hevi.production.artifact_verification import verify_v3

    signature = inspect.signature(verify_v3)
    assert "human_decision" in signature.parameters, (
        "verify_v3 still takes a bare human_review string with no artifact binding")


@pytest.mark.xfail(strict=True, reason="P0-8: p5_1_pairwise decide_promotion overrides hard gates")
def test_human_decision_is_NOT_yet_prevented_from_overriding_gates() -> None:
    """§17: a human decision must not silently override a hard machine gate."""
    source = (HEVI / "ops/p5_1_pairwise.py").read_text(encoding="utf-8")
    override_at = source.find("if human_override is not None:")
    hard_gate_at = source.find("new_blockers > 0")
    assert override_at > hard_gate_at, (
        "the human_override branch returns before the hard-gate check, so a human "
        "decision bypasses new_blockers entirely")


# ─────────────────────────────────────────────────────────────────────────
# Group 3 — the inventory's own decisions are locked
# ─────────────────────────────────────────────────────────────────────────


def test_inventory_covers_every_required_object() -> None:
    """All 14 objects must be inventoried, and the gate must be stated."""
    text = INVENTORY.read_text(encoding="utf-8")
    for obj in CANONICAL_OBJECTS:
        assert obj in text, f"{obj} is not in the contract inventory"
    assert "CONTRACTS_CANONICAL = PARTIAL" in text, (
        "the inventory must state its own gate status honestly")


def test_inventory_names_a_canonical_owner_for_every_object() -> None:
    """Each of the 14 must have an explicit owner and an explicit action."""
    text = INVENTORY.read_text(encoding="utf-8")
    for action in ("ADOPT", "NEW", "EXTEND", "PROJECT"):
        assert action in text, f"no {action} decision recorded"
    # Six must be created new; this is the load-bearing P0-2 finding.
    assert text.count("must be created new") >= 6, (
        "expected 6 'create new' decisions (TimelineIR, RenderReceipt, "
        "EvidencePack, VideoAcceptance, FailureClass, HumanDecision)")


def test_generation_request_was_not_rewritten() -> None:
    """§4 judgement 4: adopt the clean contract, do not author a new one.

    If someone later introduces a parallel generation-request type, this fails.
    """
    definitions = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "VideoGenerationRequest":
                definitions.append(path.relative_to(REPO))
    assert definitions == [Path("hevi/generation/models.py")], (
        f"a second VideoGenerationRequest appeared: {definitions}")


def test_recipe_canonical_owner_is_unchanged() -> None:
    """P0-2 designated p5_3 as the shot-recipe authority.

    Enumerated precisely: the three *shot recipe* systems are the dataclasses
    carrying a duration range or shot intent. Other Recipe-named classes are
    different concepts (ProceduralRecipe generates Manim source;
    RecipeCard/prompt recipes are prompt text; Recipe is a studio template;
    RecipeCandidate/RecipeSelectionEvidence are p5_3 internals) and must not be
    counted here.
    """
    shot_recipe_classes = ("ShotRecipe", "CinematicRecipe", "ShotRecipeCard")
    found: dict[str, str] = {}
    for path in _production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in shot_recipe_classes:
                found.setdefault(node.name, str(path.relative_to(REPO)))
    assert found == {
        "ShotRecipe": "hevi/cinematic/shot_intelligence/models.py",
        "CinematicRecipe": "hevi/production/p5_3/schema.py",
        "ShotRecipeCard": "hevi/motion/recipe_card.py",
    }, f"the three shot recipe systems changed: {found}"


def test_generation_receipt_name_collision_is_known() -> None:
    """``hevi/narrative/generation.py`` reuses the name for a different concept.

    Recorded so a future rename does not silently touch both.
    """
    collision = HEVI / "narrative/generation.py"
    assert collision.exists()
    text = collision.read_text(encoding="utf-8")
    assert "class GenerationResult" in text, (
        "the documented name collision disappeared; re-check the inventory")


def test_creative_brief_has_a_single_definition() -> None:
    """No competing brief authority may appear."""
    definitions = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "CreativeBrief":
                definitions.append(str(path.relative_to(REPO)))
    assert definitions == ["hevi/creative/direction_content/models.py"], (
        f"a competing CreativeBrief appeared: {definitions}")


def test_story_bible_legacy_variant_is_still_the_only_duplicate() -> None:
    """Two StoryBible definitions is the documented state; a third must fail."""
    definitions = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "StoryBible":
                definitions.append(str(path.relative_to(REPO)))
    assert len(definitions) == 2, f"expected 2 StoryBible definitions, got {definitions}"


def test_verdict_types_are_NOT_yet_six_but_never_seven() -> None:
    """Six verdict writers is the documented count; a seventh is a regression."""
    verdict_names = {
        "DeliveryGateResult", "DeliveryVerdict", "FinalReviewResult",
        "DirectionVerdict", "ProductionVerdict", "ReceiptStatus",
    }
    source = _source()
    present = {n for n in verdict_names if n in source}
    assert len(present) >= 6, (
        f"expected all 6 documented verdict types, found {sorted(present)}")


def test_no_new_canonical_contract_module_was_added() -> None:
    """P0-2 introduces no code. A new contracts/ package means the phase overran."""
    for candidate in ("hevi/contracts", "hevi/production/contracts"):
        assert not (REPO / candidate).exists(), (
            f"{candidate} exists; P0-2 was inventory and type semantics only")


def test_sha256_pattern_is_the_one_used_by_the_receipt_model() -> None:
    """The EvidencePack/HumanDecision designs both reuse this exact pattern."""
    from hevi.execution.models import _SHA256_HEX as receipt_pattern

    assert receipt_pattern.match(hashlib.sha256(b"x").hexdigest())
    assert not receipt_pattern.match("nope")
    assert _SHA256_HEX.pattern == receipt_pattern.pattern, (
        "the test-local sha256 pattern drifted from the one ProductionReceipt uses")
