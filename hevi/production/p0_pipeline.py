"""HEVI P0 Canonical Production Pipeline — core types and orchestration.

This module implements the single authoritative production chain:
Narration → Voice → AudioLock → Alignment → TimelineLock → VisualIntent
→ AssetResolution → ShotPlan → MotionPlan → 15s Proof → Proof QA
→ Full Render → Final QA → COMPLETED

No duplicate orchestrators, no duplicate QA authorities.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hevi.production.audio_master_clock_workflow import execute_audio_master_clock_task
from hevi.production.delivery_gate import assert_explainer_compose, probe_video
from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
from hevi.production.p7.asset_requirement import AssetRequirement
from hevi.production.shot_readiness import AssetCandidate, ShotPreparation
from hevi.production.subtitle_timeline_workflow import execute_subtitle_timeline_task
from hevi.production.visual_quality_workflow import execute_visual_quality_task

if TYPE_CHECKING:
    from hevi.creative.autonomous.selection import ShotResolution


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ──────────────────────────────────────────────────────────────────────
# AUDIO LOCK
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AudioLock:
    """Immutable audio identity + revision + lineage."""
    audio_lock_id: str
    source_text: str
    tts_provider: str
    tts_voice: str
    audio_path: str
    audio_sha256: str
    duration_s: float
    revision: int
    lineage: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def verify_integrity(self) -> bool:
        """Verify audio file exists and hash matches."""
        p = Path(self.audio_path)
        return p.is_file() and _sha256(p) == self.audio_sha256


# ──────────────────────────────────────────────────────────────────────
# TIMELINE LOCK
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TimelineLock:
    """Immutable timeline bound to a specific AudioLock revision."""
    timeline_lock_id: str
    audio_lock_id: str
    audio_lock_revision: int
    audio_sha256: str
    subtitle_path: str
    subtitle_sha256: str
    cue_count: int
    drift_ms: int
    revision: int
    created_at: str = field(default_factory=_now)

    def verify_against(self, audio_lock: AudioLock) -> bool:
        """Fail-closed: timeline must match the exact AudioLock revision + hash."""
        return (
            self.audio_lock_id == audio_lock.audio_lock_id
            and self.audio_lock_revision == audio_lock.revision
            and self.audio_sha256 == audio_lock.audio_sha256
        )


# ──────────────────────────────────────────────────────────────────────
# VISUAL INTENT
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VisualIntent:
    """Semantic grounding for one visual segment — what must be shown and why."""
    intent_id: str
    timeline_lock_id: str
    narration_segment: str
    start_s: float
    end_s: float
    required_entities: tuple[str, ...]
    required_concepts: tuple[str, ...]
    visual_purpose: str
    motion_purpose: str
    forbidden_substitutes: tuple[str, ...] = field(default_factory=tuple)
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def covers_narration(self, text: str) -> bool:
        """Check if narration segment is semantically covered."""
        return self.narration_segment.lower() in text.lower()


# ──────────────────────────────────────────────────────────────────────
# RESOLVED ASSET
# ──────────────────────────────────────────────────────────────────────

# ── P1:discovery 层的 scorer 与 identity ──────────────────────────────────
# discovery 只产出候选;相关性分必须声明适用域(S3 契约),域外不可用而非低分。
# 关键词表仍是黑洞/NASA 专用的(F2,见 docs/p10/p1_entry_audit.md),本阶段不通用化。
P0_ASSET_DOMAIN = "science_nasa"
P0_SCORER_ID = "p0.science_keyword"
P0_KEYWORD_RELEVANCE = {
    "black hole": 0.95, "accretion": 0.92, "binary": 0.88, "orbit": 0.85,
}


class P0_ScienceRelevanceScorer:
    """按命中关键词给出相关性,并声明只适用于 science_nasa 域。

    未命中任何关键词 → 返回 0.0,但该候选本不该出现(discovery 只在命中时建候选)。
    """

    applicable_domains = frozenset({P0_ASSET_DOMAIN})

    def __call__(self, candidate: AssetCandidate) -> float:
        # 分数来自关键词命中强度;候选的 asset_ref 携带命中文件名。
        for keyword, relevance in P0_KEYWORD_RELEVANCE.items():
            if keyword and relevance and keyword in candidate.asset_ref.lower():
                return relevance
        return 0.0


def _canonical_seam() -> tuple[Any, Any, Any, Any]:
    """取 canonical selection seam(延迟导入,见 `_canonical_seam_doc`)。

    延迟导入的原因:`hevi.creative.autonomous.__init__` → `canonical.py` 反向 import
    本模块的 `VisualIntent`,所以本模块**不能**在 import 期引入 autonomous 包
    (会得到 `ImportError: partially initialized`)。该反向边是 S1 遗留,
    不在 P1 范围内修复。
    """
    from hevi.creative.autonomous.identity import RequirementBinding, RequirementBindingSet
    from hevi.creative.autonomous.selection import admit_generation, resolve

    return RequirementBinding, RequirementBindingSet, resolve, admit_generation


def _acquisition_seam() -> tuple[Any, Any]:
    """取 acquisition 能力(延迟导入,理由同 `_canonical_seam`)。

    返回 (StockAssetAcquirer 类, evaluate_provider_policy)。仅用于类型标注与
    provider policy 调用;不导出符号到本模块命名空间。
    """
    from hevi.creative.autonomous.acquire_stock import StockAssetAcquirer
    from hevi.provider_policy.policy import evaluate_provider_policy

    return StockAssetAcquirer, evaluate_provider_policy


async def _acquire_for_unresolved(
    stock_acquirer: Any | None,
    requirement: AssetRequirement,
    unresolved_requirement_ids: tuple[str, ...],
) -> tuple[AssetCandidate, ...]:
    """P2-A:为 unresolved requirement 走 stock acquisition,返回**候选**。

    fail-closed 三处:provider policy 选不出 provider、检索异常、单条物化异常
    —— 全部返回空,让 resolution 保持 unresolved。绝不返回「已搞定」。
    """
    if stock_acquirer is None:
        return ()
    if requirement.requirement_id not in unresolved_requirement_ids:
        return ()
    _, evaluate_provider_policy = _acquisition_seam()
    decision = await evaluate_provider_policy(
        _stock_provider_policy(stock_acquirer.provider_id),
        catalogue=stock_acquirer.provider_catalogue(),
    )
    if decision.selected_provider is None:
        return ()
    proposed = await stock_acquirer.propose(requirement)
    return tuple(normalized.candidate for normalized in proposed)


def _stock_provider_policy(provider_id: str) -> Any:
    """stock provider 的 provider policy。只声明候选集,不设门槛。"""
    from hevi.provider_policy.policy import ProviderPolicy

    return ProviderPolicy(candidates=[provider_id], quality_floor=0)


async def _resolve_with_acquisition(
    shot_id: str,
    requirement: AssetRequirement,
    candidates: list[AssetCandidate],
    stock_acquirer: Any | None,
) -> tuple[ShotPreparation, ShotResolution, dict[str, Any]]:
    """P2-A 完整闭环。生产与验收测试走**同一段**代码。

    ```text
    resolve → unresolved → stock acquire → validate → 重新 resolve
    ```

    第三返回值是 acquisition 事件说明(供 gate 记录);它**不参与**任何取舍判断。

    关键纪律:acquire 成功只等于「多了候选」。新候选必须再过一次 canonical
    scorer + selector 才可能成为 selected —— 「拿到文件」不等于「可以生成」。
    """
    preparation = _shot_preparation(shot_id, requirement, candidates)
    resolution = _resolve_shot(preparation, requirement)
    note: dict[str, Any] = {"attempted": False, "acquired": 0, "reason": ""}
    if not resolution.unresolved_requirement_ids:
        return preparation, resolution, note

    note["attempted"] = True
    note["reason"] = "NO_ACQUIRER_CONFIGURED" if stock_acquirer is None else "ACQUIRED"
    acquired = await _acquire_for_unresolved(
        stock_acquirer, requirement, resolution.unresolved_requirement_ids)
    note["acquired"] = len(acquired)
    if acquired:
        preparation = _shot_preparation(
            shot_id, requirement, [*candidates, *acquired])
        # 重新 resolve:新候选要经过 canonical scorer + selector。
        resolution = _resolve_shot(preparation, requirement)
        note["reason"] = "RE_RESOLVED"
    return preparation, resolution, note


def _shot_preparation(
    shot_id: str, requirement: AssetRequirement, candidates: list[AssetCandidate],
) -> ShotPreparation:
    """候选 → ShotPreparation。local ref 与 canonical id 分处两个 namespace。"""
    return ShotPreparation(
        shot_id=shot_id,
        candidates=candidates,
        required_asset_refs=[c.asset_ref for c in candidates],
    )


def _resolve_shot(preparation: ShotPreparation, requirement: AssetRequirement) -> ShotResolution:
    """canonical resolve —— 唯一一次「谁被选」的判定。"""
    RequirementBinding, RequirementBindingSet, resolve, _ = _canonical_seam()
    bindings = RequirementBindingSet(tuple(
        RequirementBinding(local_ref=c.asset_ref, requirement=requirement)
        for c in preparation.candidates
    ))
    # `_canonical_seam()` 是延迟导入(见其 docstring),类型信息在此显式恢复。
    return cast("ShotResolution", resolve(
        preparation,
        domain=P0_ASSET_DOMAIN,
        scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
        bindings=bindings,
        # 零候选的 requirement 必须报 unresolved,否则 acquisition 没有输入。
        required_requirement_ids=(requirement.requirement_id,),
    ))


def _requirement_for(intent: VisualIntent) -> AssetRequirement:
    """VisualIntent → canonical p7 requirement id。

    canonical identity 是 `p7.AssetRequirement.requirement_id`(由 media_type/role 派生),
    这里用它而不是自造字符串,避免出现第二个 identity namespace。
    """
    role = (AssetSemanticRole.CHARACTER if intent.required_entities
            else AssetSemanticRole.SCENE)
    return AssetRequirement(media_type=MediaType.VIDEO, semantic_role=role)


@dataclass(frozen=True)
class ResolvedAsset:
    """Verified asset with provenance, bound to VisualIntent."""
    asset_id: str
    intent_id: str
    source_uri: str
    source_sha256: str
    media_type: str
    provenance: dict[str, Any]
    semantic_relevance: float  # 0.0–1.0
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def verify_provenance(self) -> bool:
        """Verify asset file exists and hash matches provenance."""
        p = Path(self.source_uri.replace("file://", ""))
        return p.is_file() and _sha256(p) == self.source_sha256


# ──────────────────────────────────────────────────────────────────────
# SHOT PLAN
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ShotPlan:
    """Single shot bound to timeline + intent + asset."""
    shot_id: str
    timeline_lock_id: str
    visual_intent_id: str
    resolved_asset_id: str
    start_s: float
    end_s: float
    shot_size: str  # wide/medium/closeup/extreme_closeup
    camera_setup: str
    revision: int = 1
    created_at: str = field(default_factory=_now)


# ──────────────────────────────────────────────────────────────────────
# MOTION PLAN
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MotionPlan:
    """Motion specification serving semantic purpose."""
    motion_id: str
    shot_id: str
    visual_intent_id: str
    motion_type: str  # ken_burns/pan/zoom/static/parallax
    motion_params: dict[str, Any]
    semantic_justification: str
    revision: int = 1
    created_at: str = field(default_factory=_now)


# ──────────────────────────────────────────────────────────────────────
# PRODUCTION GATE REPORT
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ProductionGateReport:
    """Aggregated gate results for one production pass."""
    production_id: str
    gates: dict[str, bool] = field(default_factory=dict)
    gate_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    failed_gates: list[str] = field(default_factory=list)
    proof_mp4: str = ""
    final_mp4: str = ""
    contact_sheet: str = ""
    created_at: str = field(default_factory=_now)

    def record(self, gate: str, passed: bool, details: dict[str, Any] | None = None) -> None:
        self.gates[gate] = passed
        if details:
            self.gate_details[gate] = details
        if not passed:
            self.failed_gates.append(gate)

    def all_pass(self) -> bool:
        return all(self.gates.values()) and bool(self.gates)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ──────────────────────────────────────────────────────────────────────

@dataclass
class P0ProductionState:
    """Mutable state for one production run."""
    production_id: str
    narration: str
    topic: str
    language: str = "en-US"
    voice: str = "en-US-AriaNeural"

    # Pipeline artifacts
    audio_lock: AudioLock | None = None
    timeline_lock: TimelineLock | None = None
    visual_intents: list[VisualIntent] = field(default_factory=list)
    resolved_assets: list[ResolvedAsset] = field(default_factory=list)
    shot_plans: list[ShotPlan] = field(default_factory=list)
    # P1:唯一 selection authority 的结论。generation admission 只读它。
    shot_resolutions: dict[str, Any] = field(default_factory=dict)
    motion_plans: list[MotionPlan] = field(default_factory=list)

    # Gate report
    report: ProductionGateReport | None = None

    # Proof/final artifacts
    proof_mp4: str = ""
    final_mp4: str = ""

    def __post_init__(self) -> None:
        if self.report is None:
            self.report = ProductionGateReport(production_id=self.production_id)

    def gate(self, gate: str, passed: bool, details: dict[str, Any] | None = None) -> None:
        """P1:canonical resolution 专用记录入口。

        与既有 `state.report.record(...)` 等价,额外做非空收窄 —— P1 新增的
        SHOT_RESOLUTION / ASSET_RELEVANCE 门要读 `ready_for_generation`,不能
        在 report 可能为 None 的情况下静默跳过记录。
        """
        assert self.report is not None
        self.report.record(gate, passed, details)


async def run_p0_production(
    narration: str,
    topic: str,
    output_dir: Path,
    language: str = "en-US",
    voice: str = "en-US-AriaNeural",
    max_proof_seconds: int = 15,
    stock_acquirer: Any | None = None,
) -> P0ProductionState:
    """P0 全流程。

    `stock_acquirer`:P2-A 的 stock acquisition 能力。`None`(默认)= 不做 fallback,
    unresolved 的镜次不会生成 —— fail closed,而不是「悄悄用旧结论生成」。
    """
    """Execute the full P0 canonical production chain."""
    production_id = f"p0-{uuid.uuid4().hex[:12]}"
    state = P0ProductionState(
        production_id=production_id,
        narration=narration,
        topic=topic,
        language=language,
        voice=voice,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. AUDIO LOCK ──────────────────────────────────────────────
    audio_task = {
        "id": f"{production_id}:audio",
        "topic": topic,
        "config_json": {
            "production_id": production_id,
            "text": narration,
            "language": language,
            "language_code": language[:2],
            "fps": 24,
            "asr_model_dir": str(Path.home() / "models/faster-whisper-large-v3-turbo"),
            "voice_identity": {
                "voice_id": "en_female_standard",
                "binding": "prompt",
                "description": "HEVI P0 qualification voice",
            },
            "output_dir": str(out_dir / "audio"),
        },
    }
    audio_result = await execute_audio_master_clock_task(audio_task, pool=None)
    if audio_result.get("status") != "completed":
        raise RuntimeError(f"AudioLock failed: {audio_result.get('error')}")

    audio_config = audio_result.get("config_json") or {}
    audio_artifacts = audio_config.get("artifact_manifest", {}).get("artifacts", [])
    tts_art = next((a for a in audio_artifacts if a.get("logical_role") == "tts_audio"), None)
    if not tts_art:
        raise RuntimeError("AudioLock: no tts_audio artifact produced")

    audio_path = Path(tts_art["path"])
    audio_sha = tts_art["sha256"]
    audio_dur = tts_art.get("metadata", {}).get("duration_s", 0)

    state.audio_lock = AudioLock(
        audio_lock_id=f"{production_id}:audiolock",
        source_text=narration,
        tts_provider="edge_tts",
        tts_voice=voice,
        audio_path=str(audio_path),
        audio_sha256=audio_sha,
        duration_s=audio_dur,
        revision=1,
        lineage={"audio_task_id": audio_task["id"]},
    )
    state.report.record("AUDIO_LOCK", state.audio_lock.verify_integrity(), {
        "audio_sha256": audio_sha, "duration_s": audio_dur
    })

    # ── 2. TIMELINE LOCK (subtitle alignment) ─────────────────────
    timeline_artifacts = audio_config.get("artifact_manifest", {}).get("artifacts", [])
    srt_art = next((a for a in timeline_artifacts if a.get("logical_role") == "subtitle_srt"), None)
    if not srt_art:
        subtitle_task = {
            "id": f"{production_id}:subtitle",
            "topic": topic,
            "config_json": {
                "source_audio_path": str(audio_path),
                "source_audio_sha256": audio_sha,
                "language_code": language[:2],
                "output_dir": str(out_dir / "subtitles"),
            },
        }
        subtitle_result = await execute_subtitle_timeline_task(subtitle_task, pool=None)
        if subtitle_result.get("status") != "completed":
            raise RuntimeError(f"TimelineLock failed: {subtitle_result.get('error')}")
        sub_config = subtitle_result.get("config_json") or {}
        sub_artifacts = sub_config.get("artifact_manifest", {}).get("artifacts", [])
        srt_art = next((a for a in sub_artifacts if a.get("logical_role") == "subtitle_srt"), None)

    if not srt_art:
        raise RuntimeError("TimelineLock: no subtitle_srt artifact produced")

    srt_path = Path(srt_art["path"])
    srt_sha = srt_art["sha256"]
    srt_text = srt_path.read_text(encoding="utf-8")
    cue_count = srt_text.count("-->")

    state.timeline_lock = TimelineLock(
        timeline_lock_id=f"{production_id}:timelinelock",
        audio_lock_id=state.audio_lock.audio_lock_id,
        audio_lock_revision=state.audio_lock.revision,
        audio_sha256=audio_sha,
        subtitle_path=str(srt_path),
        subtitle_sha256=srt_sha,
        cue_count=cue_count,
        drift_ms=srt_art.get("metadata", {}).get("clock_drift_ms", 0),
        revision=1,
    )
    tl_ok = state.timeline_lock.verify_against(state.audio_lock)
    state.report.record("TIMELINE_LOCK", tl_ok, {
        "cue_count": cue_count, "drift_ms": state.timeline_lock.drift_ms
    })

    # CAPTION_SYNC: subtitles aligned to audio master clock
    caption_sync_ok = abs(state.timeline_lock.drift_ms) <= 100
    state.report.record("CAPTION_SYNC", caption_sync_ok, {
        "cue_count": cue_count,
        "drift_ms": state.timeline_lock.drift_ms,
        "audio_duration_s": state.audio_lock.duration_s,
    })

    # ── 3. VISUAL INTENT SET ──────────────────────────────────────
    sentences = [s.strip() for s in narration.replace("。", ".").split(".") if s.strip()]
    if not sentences:
        sentences = [narration]

    segment_duration = state.audio_lock.duration_s / len(sentences)
    for i, sent in enumerate(sentences):
        intent = VisualIntent(
            intent_id=f"{production_id}:intent-{i}",
            timeline_lock_id=state.timeline_lock.timeline_lock_id,
            narration_segment=sent,
            start_s=i * segment_duration,
            end_s=(i + 1) * segment_duration,
            required_entities=tuple(_extract_entities(sent)),
            required_concepts=tuple(_extract_concepts(sent)),
            visual_purpose=f"Visualize: {sent[:80]}",
            motion_purpose=f"Motion supporting: {sent[:80]}",
            forbidden_substitutes=("generic_stars", "title_card_only", "large_explanatory_text"),
        )
        state.visual_intents.append(intent)

    state.report.record("VISUAL_GROUNDING", len(state.visual_intents) > 0, {
        "intent_count": len(state.visual_intents)
    })
    state.report.record("TEXT_DOMINANCE", not _has_large_explanatory_text(narration), {
        "check": "no large explanatory text blocks"
    })

    # ── 4. ASSET RESOLUTION ───────────────────────────────────────
    asset_base = Path("/tmp/hevi-science-v3/assets")
    nasa_assets = {
        "black hole": "nasa_accretion.webm",
        "accretion": "nasa_accretion.webm",
        "binary": "nasa_binary.webm",
        "orbit": "nasa_orrery.webm",
    }

    intent_candidates: dict[str, list[AssetCandidate]] = {}
    for intent in state.visual_intents:
        # P1:discovery 只**产出候选**,不再自行决定选哪个(去掉 break + 硬编码 0.95)。
        # 选择权移交 canonical scorer + selector(resolve)。
        candidates: list[AssetCandidate] = []
        seen_files: set[str] = set()
        text = intent.narration_segment.lower()
        for keyword, asset_file in nasa_assets.items():
            if keyword not in text or asset_file in seen_files:
                continue
            asset_path = asset_base / asset_file
            if not asset_path.exists():
                continue
            seen_files.add(asset_file)
            candidates.append(AssetCandidate(
                candidate_id=f"{production_id}:cand-{intent.intent_id[-4:]}-{asset_file}",
                requirement_id=_requirement_for(intent).requirement_id,
                asset_ref=asset_path.as_uri(),
                confidence=0.0,  # 由 canonical scorer 生产(P1:不再硬编码 0.95)
                verified=True,  # 文件存在;canonical selector 再判门槛
            ))
        intent_candidates[intent.intent_id] = candidates
        matched = bool(candidates)
        if not matched:
            state.gate("ASSET_RELEVANCE", False, {
                "intent": intent.intent_id, "reason": "no semantically relevant asset"
            })

    # ── 4b. CANONICAL RESOLUTION (P1) + ACQUISITION FALLBACK (P2-A) ──
    # 唯一 selection authority。打分/选择/identity 绑定全在 canonical 层完成;
    # 本层只负责提供候选、声明适用域、跑 acquisition,不参与「选哪个」。
    #
    # 顺序不可颠倒(P2):
    #   resolve → unresolved → acquire → validate → **重新 resolve** → admit
    # Acquirer 永远不宣布成功;它只产出候选。选谁仍由 scorer → selector 决定。
    admit_generation = _canonical_seam()[3]
    for intent in state.visual_intents:
        requirement = _requirement_for(intent)
        shot_id = f"{production_id}:shot-{intent.intent_id[-4:]}"
        preparation, resolution, note = await _resolve_with_acquisition(
            shot_id, requirement, intent_candidates.get(intent.intent_id, []),
            stock_acquirer)
        if note["attempted"]:
            state.gate("ASSET_ACQUISITION_ATTEMPTED", note["acquired"] > 0, {
                "intent": intent.intent_id, **note,
            })
        state.shot_resolutions[resolution.shot_id] = resolution
        state.gate("SHOT_RESOLUTION", resolution.ready_for_generation, {
            "intent": intent.intent_id,
            "selected": list(resolution.selected_requirement_ids),
            "unresolved": list(resolution.unresolved_requirement_ids),
            "unbound": list(resolution.unbound_asset_refs),
            "human_review": resolution.human_review_required,
        })
        if not resolution.ready_for_generation:
            continue
        # generation 只经 admission seam 拿资产。
        selected = admit_generation(resolution, preparation.candidates)
        asset_path = Path(selected.asset_ref.replace("file://", ""))
        state.resolved_assets.append(ResolvedAsset(
            asset_id=f"{production_id}:asset-{intent.intent_id[-4:]}",
            intent_id=intent.intent_id,
            source_uri=selected.asset_ref,
            source_sha256=_sha256(asset_path),
            media_type="video/webm",
            provenance={"source": "NASA", "file": asset_path.name,
                        "scored_by": selected.scored_by,
                        "candidate_id": selected.candidate_id},
            semantic_relevance=selected.confidence,
        ))

    # ── 5. SHOT PLAN ──────────────────────────────────────────────
    for intent in state.visual_intents:
        # P1 (Invariant A/D):generation admission 只认 ShotResolution。
        # 不再从 resolved_assets 重新推导「其实可以生成」。
        found = state.shot_resolutions.get(f"{production_id}:shot-{intent.intent_id[-4:]}")
        if found is None or not found.ready_for_generation:
            continue
        admit: ShotResolution = found
        asset = next((a for a in state.resolved_assets if a.intent_id == intent.intent_id), None)
        if not asset:
            continue
        shot = ShotPlan(
            shot_id=admit.shot_id,
            timeline_lock_id=state.timeline_lock.timeline_lock_id,
            visual_intent_id=intent.intent_id,
            resolved_asset_id=asset.asset_id,
            start_s=intent.start_s,
            end_s=intent.end_s,
            shot_size="medium",
            camera_setup="static",
        )
        state.shot_plans.append(shot)

    state.report.record("SHOT_PACING", len(state.shot_plans) > 0, {
        "shot_count": len(state.shot_plans)
    })

    # ── 6. MOTION PLAN ────────────────────────────────────────────
    for shot in state.shot_plans:
        shot_intent = next((i for i in state.visual_intents
                            if i.intent_id == shot.visual_intent_id), None)
        if shot_intent is None:
            continue
        motion = MotionPlan(
            motion_id=f"{production_id}:motion-{shot.shot_id[-4:]}",
            shot_id=shot.shot_id,
            visual_intent_id=shot_intent.intent_id,
            motion_type="ken_burns",
            motion_params={"zoom": 1.2, "pan": "slow"},
            semantic_justification=f"Support visual purpose: {shot_intent.visual_purpose}",
        )
        state.motion_plans.append(motion)

    state.report.record("MOTION_PURPOSE", len(state.motion_plans) > 0, {
        "motion_count": len(state.motion_plans)
    })

    # ── 7. 15s PROOF ──────────────────────────────────────────────
    proof_dir = out_dir / "proof"
    proof_dir.mkdir(exist_ok=True)

    motion_spec = {
        "duration_s": min(max_proof_seconds, state.audio_lock.duration_s),
        "fps": 24,
        "width": 1280,
        "height": 720,
        "shots": [
            {
                "shot_id": s.shot_id,
                "start_s": s.start_s,
                "end_s": s.end_s,
                "asset_uri": next(a.source_uri for a in state.resolved_assets if a.asset_id == s.resolved_asset_id),
                "motion_type": next(m.motion_type for m in state.motion_plans if m.shot_id == s.shot_id),
                "motion_params": next(m.motion_params for m in state.motion_plans if m.shot_id == s.shot_id),
            }
            for s in state.shot_plans
        ],
        "audio_path": state.audio_lock.audio_path,
        "subtitle_path": state.timeline_lock.subtitle_path,
    }

    proof_spec_path = proof_dir / "motion_spec.json"
    proof_spec_path.write_text(json.dumps(motion_spec, indent=2))

    proof_task = {
        "id": f"{production_id}:proof",
        "topic": topic,
        "config_json": {
            "motion_spec_path": str(proof_spec_path),
            "output_dir": str(proof_dir),
            "source_audio_path": state.audio_lock.audio_path,
            "source_audio_sha256": state.audio_lock.audio_sha256,
            "source_subtitle_path": state.timeline_lock.subtitle_path,
            "max_duration_s": max_proof_seconds,
        },
    }
    proof_result = await execute_visual_quality_task(proof_task, pool=None)

    if proof_result.get("status") != "completed":
        state.report.record("15S_PROOF", False, {"reason": proof_result.get("error")})
        state.report.record("FULL_RENDER", False, {"reason": "proof failed, full render blocked"})
        state.report.record("FINAL_QA", False, {"reason": "proof failed"})
        return state

    proof_config = proof_result.get("config_json") or {}
    proof_artifacts = proof_config.get("artifact_manifest", {}).get("artifacts", [])
    final_art = next((a for a in proof_artifacts if a.get("primary") and a.get("kind") == "video"), None)
    if not final_art:
        state.report.record("15S_PROOF", False, {"reason": "no proof video artifact"})
        return state

    state.proof_mp4 = final_art["path"]
    state.report.record("15S_PROOF", True, {"proof_mp4": state.proof_mp4})

    # ── 8. PROOF QA ───────────────────────────────────────────────
    proof_probe = probe_video(state.proof_mp4)
    proof_qa_pass = (
        proof_probe.has_video
        and proof_probe.has_audio
        and proof_probe.duration_s > 0
        and abs(proof_probe.duration_s - min(max_proof_seconds, state.audio_lock.duration_s)) < 2.0
    )
    state.report.record("CAPTION_SYNC", proof_qa_pass, {"duration_s": proof_probe.duration_s})
    state.report.record("SOURCE_PROVENANCE", len(state.resolved_assets) == len(state.visual_intents), {
        "resolved": len(state.resolved_assets), "required": len(state.visual_intents)
    })

    if not proof_qa_pass:
        state.report.record("FULL_RENDER", False, {"reason": "proof QA failed, full render blocked"})
        state.report.record("FINAL_QA", False, {"reason": "proof QA failed"})
        return state

    # ── 9. FULL RENDER ────────────────────────────────────────────
    full_dir = out_dir / "full"
    full_dir.mkdir(exist_ok=True)

    full_spec = dict(motion_spec)
    full_spec["duration_s"] = state.audio_lock.duration_s

    full_spec_path = full_dir / "motion_spec.json"
    full_spec_path.write_text(json.dumps(full_spec, indent=2))

    full_task = {
        "id": f"{production_id}:full",
        "topic": topic,
        "config_json": {
            "motion_spec_path": str(full_spec_path),
            "output_dir": str(full_dir),
            "source_audio_path": state.audio_lock.audio_path,
            "source_audio_sha256": state.audio_lock.audio_sha256,
            "source_subtitle_path": state.timeline_lock.subtitle_path,
        },
    }
    full_result = await execute_visual_quality_task(full_task, pool=None)

    if full_result.get("status") != "completed":
        state.report.record("FULL_RENDER", False, {"reason": full_result.get("error")})
        state.report.record("FINAL_QA", False, {"reason": "full render failed"})
        return state

    full_config = full_result.get("config_json") or {}
    full_artifacts = full_config.get("artifact_manifest", {}).get("artifacts", [])
    final_art = next((a for a in full_artifacts if a.get("primary") and a.get("kind") == "video"), None)
    if not final_art:
        state.report.record("FULL_RENDER", False, {"reason": "no final video artifact"})
        state.report.record("FINAL_QA", False, {"reason": "full render failed"})
        return state

    state.final_mp4 = final_art["path"]
    state.report.record("FULL_RENDER", True, {"final_mp4": state.final_mp4})

    # ── 10. FINAL QA ──────────────────────────────────────────────
    final_probe = probe_video(state.final_mp4)
    final_qa_pass = (
        final_probe.has_video
        and final_probe.has_audio
        and final_probe.duration_s > 0
        and abs(final_probe.duration_s - state.audio_lock.duration_s) < 2.0
    )
    try:
        assert_explainer_compose(state.final_mp4, expected_duration_s=final_probe.duration_s)
        compose_ok = True
    except Exception:
        compose_ok = False

    state.report.record("FINAL_QA", final_qa_pass and compose_ok, {
        "duration_s": final_probe.duration_s,
        "compose_ok": compose_ok,
    })

    state.report.proof_mp4 = state.proof_mp4
    state.report.final_mp4 = state.final_mp4

    return state


def _extract_entities(text: str) -> list[str]:
    keywords = [
        "black hole", "accretion disk", "binary", "orbit", "gravity",
        "event horizon", "singularity", "spacetime", "relativity",
        "NASA", "visualization", "simulation"
    ]
    return [k for k in keywords if k in text.lower()]


def _extract_concepts(text: str) -> list[str]:
    concepts = [
        "formation", "merger", "emission", "dynamics", "visualization",
        "observation", "theory", "prediction"
    ]
    return [c for c in concepts if c in text.lower()]


def _has_large_explanatory_text(text: str) -> bool:
    visual_kw = ["black hole", "disk", "binary", "orbit", "gravity", "NASA", "visual"]
    return len(text) > 200 and not any(k in text.lower() for k in visual_kw)


__all__ = [
    "AudioLock",
    "MotionPlan",
    "MotionPlan",
    "P0ProductionState",
    "ProductionGateReport",
    "ResolvedAsset",
    "ShotPlan",
    "TimelineLock",
    "VisualIntent",
    "run_p0_production",
]
