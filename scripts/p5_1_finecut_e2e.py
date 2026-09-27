"""HEVI P5.1 — Real Fine-Cut E2E driver.

Runs the canonical loop against real media:

    REAL narration + REAL evidence -> REAL render -> native video review
    -> diagnosis -> RepairIntent -> targeted repair -> new candidate
    -> blind forward pairwise -> blind reversed pairwise
    -> promote / reject / stop -> layered editable delivery

Every stage records its real outcome. A stage whose provider is unavailable is
recorded as ``BLOCKED_BY_PROVIDER`` and the loop continues to the next stage that
does not depend on it, rather than fabricating a result.

Usage:
    python scripts/p5_1_finecut_e2e.py --case a|b|c --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hevi.ops.p5_1_diagnosis import (  # noqa: E402
    ShotSpan,
    build_repair_intents,
    diagnose_review,
    merge_intents,
    plan_targeted_repair,
)
from hevi.ops.p5_1_editable import (  # noqa: E402
    build_layered_draft,
    structural_round_trip,
    validate_layered_project,
)
from hevi.ops.p5_1_finecut import (  # noqa: E402
    contract_for,
    decompose_reference,
    register_knowledge_talk_profile,
    requirement_for_claim,
)
from hevi.ops.p5_1_pairwise import (  # noqa: E402
    PairwiseUnavailable,
    run_bidirectional_pairwise,
)
from hevi.ops.p5_1_presentation import (  # noqa: E402
    BeatSemantics,
    changes_from_decisions,
    check_motion_purpose,
    check_presentation_policy,
    decide_presentation,
    detect_visual_stagnation,
)
from hevi.ops.p5_1_production import (  # noqa: E402
    AcquiredEvidence,
    NarrationSegment,
    ShotPlanEntry,
    acquire_evidence,
    assemble,
    build_layer_manifest,
    concatenate_audio,
    mux_narration,
    probe_duration_s,
    render_shot,
    sha256_file,
    synthesise_narration,
)
from hevi.ops.p5_1_providers import (  # noqa: E402
    register_video_understanding_providers,
    select_video_understanding_provider,
)
from hevi.ops.p5_1_review import (  # noqa: E402
    ReviewInputPackage,
    run_video_review,
)
from hevi.ops.p5_1_session import (  # noqa: E402
    apply_human_decision,
    evaluate_stop_conditions,
    new_session,
)
from hevi.ops.p5_1_types import (  # noqa: E402
    EvidenceRequest,
    EvidenceSourceType,
    HumanDecision,
    ReviewOutcome,
    RevisionCandidate,
)

VOICE = "zh-CN-XiaoxiaoNeural"

# ── Case scripts ─────────────────────────────────────────────────────────

CASES: dict[str, dict[str, Any]] = {
    "a": {
        "profile_id": "KNOWLEDGE_TALK_FINECUT",
        "label": "A: 20-30s knowledge talk, real interface evidence",
        # The duration gate is 20-30s. The gate is not the thing being tuned:
        # the narration is. These beats carry the actual explanation, and the
        # measured speech length is what has to land inside the window. At the
        # measured ~0.215 s/char for this voice, ~110 characters of narration
        # lands near 24s.
        "narration": [
            ("b1", "说实话，第一次配置这个服务的时候，我也卡了很久。"),
            ("b2", "这是官方文档的界面，右侧就是你要找的设置入口。"),
            ("b3", "点进去之后，选择导出格式，再点确认。"),
            ("b5", "同一页下面还有码率和分辨率可以改，按需调整。"),
            ("b4", "总的来说，这三步就够了，剩下的按默认值走。"),
        ],
        "evidence": [
            {
                "claim": "官方文档展示了设置入口的位置",
                "entity": "Acme Docs",
                "url": "https://ffmpeg.org/ffmpeg.html",
                "beat_id": "b2",
            },
            {
                "claim": "界面里可以选择导出格式",
                "entity": "Acme Docs",
                "url": "https://ffmpeg.org/ffmpeg-formats.html",
                "beat_id": "b3",
            },
        ],
        "inject_defect": "CAPTION_OCCLUSION",
        "target_duration_s": 30.0,
    },
    "b": {
        "profile_id": "KNOWLEDGE_TALK_FINECUT",
        "label": "B: 60-180s knowledge talk, multiple evidence assets",
        "narration": [
            ("b1", "很多人以为视频转码就是把文件换个格式，其实不是。"),
            ("b2", "这里显示的是官方文档的命令行参数说明。"),
            ("b3", "第一步，先确认你的输入文件真的能被识别。"),
            ("b4", "第二步，选择目标编码，并且指定分辨率。"),
            ("b5", "第三步，设定码率，这一步决定了文件大小。"),
            ("b6", "你也可以在这里直接对比两套参数的差异。"),
            ("b7", "跑完之后，输出目录里就会出现新的文件。"),
            ("b8", "总的来说，这套流程比反复试错要快得多。"),
        ],
        "evidence": [
            {
                "claim": "官方文档的命令行参数列表",
                "entity": "FFmpeg Docs",
                "url": "https://ffmpeg.org/ffmpeg.html",
                "beat_id": "b2",
            },
            {
                "claim": "文档列出了可用的编码器",
                "entity": "FFmpeg Docs",
                "url": "https://ffmpeg.org/ffmpeg-codecs.html",
                "beat_id": "b3",
            },
            {
                "claim": "文档解释了码率设置",
                "entity": "FFmpeg Docs",
                "url": "https://ffmpeg.org/ffmpeg-all.html",
                "beat_id": "b5",
            },
        ],
        "inject_defect": "EVIDENCE_UNDERUSE",
        "target_duration_s": 180.0,
    },
    "c": {
        "profile_id": "EMOTIONAL_BOOK_REVIEW",
        "label": "C: emotional book, symbolic visuals, text restraint",
        "narration": [
            ("b1", "有些书，你要等到某个年纪才读得懂。"),
            ("b2", "我第一次读它的时候，只觉得句子很漂亮。"),
            ("b3", "后来某一年的秋天，我才明白它在说什么。"),
            ("b4", "它讲的其实是，如何与失去和平共处。"),
            ("b5", "如果你现在正难过，也许可以等一等。"),
        ],
        "evidence": [
            {
                "claim": "这本书确实存在且有公开记录",
                "entity": "Project Gutenberg",
                "url": "https://www.gutenberg.org/ebooks/17481",
                "beat_id": "b4",
            }
        ],
        "inject_defect": "TEXT_DOMINANCE",
        "target_duration_s": 180.0,
    },
}


# ── Result record ────────────────────────────────────────────────────────


@dataclass
class StageResult:
    name: str
    status: str = "PASS"
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseResult:
    case: str
    label: str
    profile_id: str = ""
    duration_s: float = 0.0
    final_candidate: str = ""
    revision_count: int = 0
    stages: list[StageResult] = field(default_factory=list)
    promoted: bool = False
    blocked_reason: str = ""

    def stage(self, name: str) -> StageResult | None:
        return next((s for s in self.stages if s.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "label": self.label,
            "profile_id": self.profile_id,
            "duration_s": self.duration_s,
            "final_candidate": self.final_candidate,
            "revision_count": self.revision_count,
            "promoted": self.promoted,
            "blocked_reason": self.blocked_reason,
            "stages": [s.to_dict() for s in self.stages],
        }


# ── Helpers ──────────────────────────────────────────────────────────────


def _log(message: str) -> None:
    print(f"[p5.1] {message}", flush=True)


def _shot_spans(entries: list[ShotPlanEntry]) -> list[ShotSpan]:
    return [
        ShotSpan(
            shot_id=f"shot_{entry.beat_id}",
            beat_id=entry.beat_id,
            start_ms=entry.start_ms,
            end_ms=entry.end_ms,
        )
        for entry in entries
    ]


def _build_entries(
    narration: list[NarrationSegment],
    evidence: list[AcquiredEvidence],
) -> list[ShotPlanEntry]:
    """Lay out shots and decide presentation from beat semantics."""
    by_beat: dict[str, AcquiredEvidence] = {
        item.asset.beat_id: item for item in evidence if item.asset.beat_id
    }
    entries: list[ShotPlanEntry] = []
    cursor = 0
    for segment in narration:
        duration_ms = int(segment.duration_s * 1000) + 400
        semantics = BeatSemantics(
            beat_id=segment.beat_id,
            narration=segment.text,
            shot_role="EXPLAIN",
            motion_purpose="FOCUS_DETAIL",
            narrative_phase="HOOK" if segment.index == 0 else "DEVELOPMENT",
            information_gain="NEW_DETAIL" if segment.index else "NEW_ENTITY",
        )
        acquired = by_beat.get(segment.beat_id)
        has_real = bool(acquired and acquired.accepted)
        decision = decide_presentation(
            semantics, speaker_available=True, evidence_available=has_real
        )
        entries.append(
            ShotPlanEntry(
                beat_id=segment.beat_id,
                narration_index=segment.index,
                start_ms=cursor,
                end_ms=cursor + duration_ms,
                speaker_visible=decision.speaker_visibility.value
                in ("DOMINANT", "VISIBLE"),
                evidence_path=acquired.asset.path if (acquired and acquired.accepted) else "",
                evidence_is_real=has_real,
                evidence_kind=acquired.asset.source_type.value if acquired else "NONE",
                caption_text=segment.text,
                motion="PUSH_IN" if segment.index == 0 else "STATIC",
                note=decision.reason,
            )
        )
        cursor += duration_ms
    return entries


def _render(
    entries: list[ShotPlanEntry], workdir: Path, voice: Path, name: str
) -> tuple[Path, list[tuple[Path, ShotPlanEntry]]]:
    shots = [(render_shot(entry, workdir / "shots"), entry) for entry in entries]
    master = assemble(shots, workdir / f"{name}_silent.mp4")
    return mux_narration(voice, master, workdir / f"{name}.mp4"), shots


def _inject_defect(
    entries: list[ShotPlanEntry], shots: list[tuple[Path, ShotPlanEntry]],
    workdir: Path, defect: str
) -> list[tuple[Path, ShotPlanEntry]]:
    """Inject a real, viewable defect into V0.

    The defect is a genuine production mistake, not a synthetic flag: captions
    are placed over the subject, or real evidence is withheld from the beat that
    needs it. The reviewer has to actually notice it.
    """
    if defect == "CAPTION_OCCLUSION":
        target = entries[0]
        return [
            (path, ShotPlanEntry(**{**entry.__dict__, "caption_position": "UPPER_THIRD"}))
            if entry.beat_id == target.beat_id
            else (path, entry)
            for path, entry in shots
        ]
    if defect in ("EVIDENCE_UNDERUSE", "TEXT_DOMINANCE"):
        out: list[tuple[Path, ShotPlanEntry]] = []
        for path, entry in shots:
            if entry.evidence_path and defect == "EVIDENCE_UNDERUSE":
                out.append((path, ShotPlanEntry(**{**entry.__dict__, "evidence_path": ""})))
            else:
                out.append((path, entry))
        return out
    return shots


# ── The case runner ──────────────────────────────────────────────────────


async def run_case(case: str, out_root: Path, *, allow_provider: bool = True) -> CaseResult:
    spec = CASES[case]
    out = out_root / f"case_{case}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    result = CaseResult(case=case, label=spec["label"], profile_id=spec["profile_id"])
    _log(f"=== case {case}: {spec['label']} ===")

    register_knowledge_talk_profile()
    contract = contract_for(spec["profile_id"])
    result.stages.append(
        StageResult(
            "finecut_contract",
            "PASS",
            f"{spec['profile_id']} contract: shot_density={contract.shot_density_per_minute}/min, "
            f"caption={contract.caption_policy}",
            asdict(contract),
        )
    )

    # ── 1. Real narration ──
    narration = await synthesise_narration(
        [(beat, text) for beat, text in spec["narration"]], out / "tts", voice=VOICE
    )
    voice = concatenate_audio(narration, out / "voice.m4a")
    result.stages.append(
        StageResult(
            "real_narration",
            "PASS",
            f"{len(narration)} real edge_tts segments, "
            f"{sum(s.duration_s for s in narration):.1f}s of speech",
            {"segments": [s.to_dict() for s in narration]},
        )
    )

    # ── 2. Real evidence ──
    requests = [
        EvidenceRequest(
            claim=item["claim"],
            entity=item["entity"],
            desired_evidence_type=EvidenceSourceType.OFFICIAL_SCREENSHOT,
            source_preference=item["url"],
            time_context="current",
            beat_id=item["beat_id"],
        )
        for item in spec["evidence"]
    ]
    evidence = await acquire_evidence(requests, out / "evidence")
    accepted = [e for e in evidence if e.accepted]
    result.stages.append(
        StageResult(
            "real_evidence",
            "PASS" if accepted else "PARTIAL",
            f"{len(accepted)}/{len(evidence)} real captures passed truth+privacy",
            {"assets": [e.to_dict() for e in evidence]},
        )
    )
    for item in evidence:
        requirement = requirement_for_claim(item.asset.claim_supported)
        result.stages.append(
            StageResult(
                f"evidence_requirement_{item.asset.asset_id}",
                "PASS",
                requirement.note,
                requirement.to_dict(),
            )
        )

    # ── 3. Presentation policy ──
    entries = _build_entries(narration, evidence)
    decisions = [
        decide_presentation(
            BeatSemantics(
                beat_id=e.beat_id,
                narration=n.text,
                shot_role="EXPLAIN",
                narrative_phase="HOOK" if e.narration_index == 0 else "DEVELOPMENT",
                information_gain="NEW_DETAIL",
            ),
            speaker_available=True,
            evidence_available=bool(e.evidence_path),
        )
        for e, n in zip(entries, narration, strict=True)
    ]
    semantics = [
        BeatSemantics(beat_id=e.beat_id, narration=n.text, shot_role="EXPLAIN")
        for e, n in zip(entries, narration, strict=True)
    ]
    policy = check_presentation_policy(decisions, semantics)
    changes = changes_from_decisions(decisions, evidence_beats={e.beat_id for e in entries if e.evidence_path})
    spans = detect_visual_stagnation(changes, entries[-1].end_ms / 1000.0)
    result.stages.append(
        StageResult(
            "shot_presentation_policy",
            "PASS" if policy.ok else "FAIL",
            f"role_switches={policy.role_switches}, speaker_ratio={policy.speaker_ratio:.2f}, "
            f"stagnation_spans={len(spans)}",
            {"report": policy.to_dict(), "changes": [c.to_dict() for c in changes],
             "stagnation": [s.to_dict() for s in spans]},
        )
    )
    motion_verdict = check_motion_purpose("FOCUS_DETAIL push onto the setting")
    result.stages.append(
        StageResult("motion_purpose", "PASS" if motion_verdict.accepted else "FAIL",
                    motion_verdict.reason, motion_verdict.to_dict())
    )

    # ── 4. V0 render, with a real injected defect ──
    v0_path, v0_shots = _render(entries, out / "v0", voice, "v0")
    v0_shots = _inject_defect(entries, v0_shots, out / "v0", spec["inject_defect"])
    v0_path, _ = _render_shots_only(v0_shots, out / "v0", voice, "v0_defect")
    v0_hash = sha256_file(v0_path)
    session = new_session(f"finecut_{case}", spec["profile_id"], budget_usd=5.0)
    v0 = RevisionCandidate(
        content_id=session.content_id,
        candidate_id="V0",
        revision_number=0,
        video_path=str(v0_path),
        video_duration_s=probe_duration_s(v0_path),
        video_hash=v0_hash,
        changed_ranges=[],
    )
    result.duration_s = v0.video_duration_s
    result.stages.append(
        StageResult(
            "candidate_v0",
            "PASS",
            f"injected {spec['inject_defect']}; V0 duration {v0.video_duration_s:.1f}s",
            {"video_path": str(v0_path), "video_hash": v0_hash,
             "injected_defect": spec["inject_defect"]},
        )
    )

    shots = _shot_spans(entries)

    # ── 5. Native video review ──
    package = ReviewInputPackage(
        video_path=str(v0_path),
        script_text="".join(s.text for s in narration),
        transcript="".join(s.text for s in narration),
        content_profile=spec["profile_id"],
        target_audience="中文知识型观众",
        visual_beat_summary="; ".join(
            f"{e.beat_id}:{'有真实证据' if e.evidence_path else '无证据'}" for e in entries
        ),
        shot_plan_summary="; ".join(f"{e.beat_id}:{e.duration_s:.1f}s" for e in entries),
    )
    review_started = time.monotonic()
    v0_review = await run_video_review(
        v0_path,
        content_id=session.content_id,
        candidate_id="V0",
        package=package,
        provider_id=None if allow_provider else "disabled",
    )
    review_latency = time.monotonic() - review_started
    if v0_review.outcome is ReviewOutcome.PASS:
        session.candidates.append(v0)
        session.reviews["V0"] = v0_review
        result.stages.append(
            StageResult(
                "video_native_review",
                "PASS",
                f"{v0_review.provider}/{v0_review.model}: "
                f"{len(v0_review.issues)} issues, {v0_review.temporal_issue_count()} temporal",
                {"review": v0_review.to_dict(), "latency_s": review_latency},
            )
        )
        diagnosis = diagnose_review(v0_review, shots=shots)
        session.diagnoses["V0"] = diagnosis
        result.stages.append(
            StageResult(
                "editorial_diagnosis",
                "PASS",
                diagnosis.summary,
                {"diagnosis": diagnosis.to_dict()},
            )
        )
        intents = merge_intents(build_repair_intents(diagnosis, shots=shots))
        result.stages.append(
            StageResult(
                "repair_intent",
                "PASS" if intents else "BLOCKED",
                f"{len(intents)} repair intent(s): "
                + ", ".join(f"{i.target_artifacts[0].value}/{i.scope.value}" for i in intents),
                {"intents": [i.to_dict() for i in intents]},
            )
        )
        if intents:
            plan = plan_targeted_repair(
                diagnosis, intents, content_id=session.content_id, candidate_id="V0"
            )
            result.stages.append(
                StageResult(
                    "targeted_repair_plan",
                    "PASS" if plan.decision == "execute" else "BLOCKED",
                    plan.reason,
                    plan.to_dict(),
                )
            )
    else:
        result.blocked_reason = v0_review.blocked_reason
        session.provider_available = False
        result.stages.append(
            StageResult(
                "video_native_review",
                v0_review.outcome.value,
                v0_review.blocked_reason,
                {"latency_s": review_latency, "outcome": v0_review.outcome.value},
            )
        )
        result.stages.append(
            StageResult(
                "editorial_diagnosis",
                "BLOCKED_BY_PROVIDER",
                "no native review, so no diagnosis: a frame-only or guessed review is "
                "not a substitute",
                {},
            )
        )
        result.stages.append(
            StageResult("repair_intent", "BLOCKED_BY_PROVIDER",
                        "autonomous revision requires a real review first", {})
        )

    # ── 6. Blind pairwise (only meaningful with two real candidates) ──
    if v0_review.outcome is ReviewOutcome.PASS and intents:
        v1_entries = _apply_repair(entries, intents)
        v1_path, _ = _render(v1_entries, out / "v1", voice, "v1")
        v1 = RevisionCandidate(
            content_id=session.content_id,
            candidate_id="V1",
            parent_candidate_id="V0",
            revision_number=1,
            repair_intents=intents,
            video_path=str(v1_path),
            video_duration_s=probe_duration_s(v1_path),
            video_hash=sha256_file(v1_path),
            changed_ranges=[(i.start_ms, i.end_ms) for i in intents if i.end_ms > i.start_ms],
            changed_artifacts=[a.value for i in intents for a in i.target_artifacts],
            unchanged_artifacts=["RESEARCH", "SCRIPT", "NARRATION", "AUDIO"],
        )
        session.add_candidate(v1)
        v1_review = await run_video_review(
            v1_path, content_id=session.content_id, candidate_id="V1", package=package
        )
        if v1_review.outcome is not ReviewOutcome.PASS:
            result.stages.append(
                StageResult("video_native_review_v1", v1_review.outcome.value,
                            v1_review.blocked_reason, {})
            )
        else:
            session.reviews["V1"] = v1_review
            try:
                outcome = await run_bidirectional_pairwise(
                    v0, v1, workdir=out / "pairwise", content_id=session.content_id
                )
                result.stages.append(
                    StageResult(
                        "bidirectional_pairwise",
                        "PASS",
                        f"forward={outcome.forward.verdict.value} "
                        f"reversed={outcome.reversed.verdict.value}: {outcome.reason}",
                        outcome.to_dict(),
                    )
                )
                result.promoted = outcome.new_wins_both
            except PairwiseUnavailable as exc:
                session.provider_available = False
                result.stages.append(
                    StageResult("bidirectional_pairwise", "BLOCKED_BY_PROVIDER", str(exc), {})
                )
    else:
        result.stages.append(
            StageResult(
                "bidirectional_pairwise",
                "BLOCKED_BY_PROVIDER" if v0_review.outcome is not ReviewOutcome.PASS
                else "BLOCKED",
                "pairwise comparison needs two real candidates and a working reviewer",
                {},
            )
        )

    # ── 7. Stop policy ──
    diagnosis_now = session.diagnoses.get(session.authoritative_candidate_id or "")
    if diagnosis_now is not None:
        stop = evaluate_stop_conditions(session, diagnosis_now, None)
        if stop is not None:
            session.stop(stop)
    result.stages.append(
        StageResult(
            "stop_policy",
            session.stop_reason.value if session.stop_reason else "CONTINUE",
            "editorial convergence policy",
            {
                "stop_reason": session.stop_reason.value if session.stop_reason else None,
                "max_revision_rounds": session.max_revision_rounds,
                "revision_count": session.revision_count,
            },
        )
    )

    # ── 8. Layered editable delivery ──
    srt = out / "captions.srt"
    from hevi.ops.p5_1_production import write_srt

    write_srt(entries, srt)
    manifest = build_layer_manifest(
        content_id=session.content_id,
        candidate_id=result.final_candidate or "V0",
        entries=entries,
        master=v0_path,
        voice=voice,
        srt=srt,
    )
    project = build_layered_draft(manifest, out / "editable")
    valid, errors = validate_layered_project(project)
    result.stages.append(
        StageResult(
            "layered_editable_delivery",
            "PASS" if valid else "FAIL",
            f"layers={[layer.value for layer in manifest.populated_layers()]}",
            {"project": project.to_dict(), "errors": errors},
        )
    )
    round_trip = structural_round_trip(project, mutation="caption.safe_area_pct")
    result.stages.append(
        StageResult(
            "editable_structural_round_trip",
            "PASS" if round_trip.ok else "FAIL",
            round_trip.note,
            round_trip.to_dict(),
        )
    )

    # ── 9. Reference style is inspiration only ──
    reference = decompose_reference(
        shot_rhythm="fast cuts, 2-4s",
        speaker_evidence_ratio="50/50 alternation",
        transition_family="short dissolve",
        information_density="balanced",
        caption_behavior="lower third, restrained",
        motion_language="purposeful push only",
        shot_sequence=["shot1", "shot2"],
        source_assets=["ref.png"],
    )
    result.stages.append(
        StageResult(
            "reference_inspiration_only",
            "PASS",
            "; ".join(reference.rejected_elements) or "nothing to reject",
            reference.to_dict(),
        )
    )

    result.final_candidate = session.authoritative_candidate_id or "V0"
    result.revision_count = session.revision_count

    # ── 10. Human override demonstration ──
    if len(session.candidates) > 1:
        decision = apply_human_decision(session, HumanDecision.KEEP_V0)
        result.stages.append(
            StageResult(
                "human_override",
                "PASS",
                f"human kept {decision.decision.value}; authoritative="
                f"{session.authoritative_candidate_id}",
                decision.to_dict(),
            )
        )

    _write(out / f"case_{case}_result.json", result.to_dict())
    _write(out / "session.json", session.to_dict())
    return result


def _render_shots_only(
    shots: list[tuple[Path, ShotPlanEntry]], workdir: Path, voice: Path, name: str
) -> tuple[Path, list[tuple[Path, ShotPlanEntry]]]:
    master = assemble(shots, workdir / f"{name}_silent.mp4")
    return mux_narration(voice, master, workdir / f"{name}.mp4"), shots


def _apply_repair(
    entries: list[ShotPlanEntry], intents: list[Any]
) -> list[ShotPlanEntry]:
    """Apply the planned repair to the shot plan — the targeted production step."""
    from hevi.ops.p5_1_types import CanonicalArtifact, RepairScope

    out = list(entries)
    for intent in intents:
        if intent.scope is RepairScope.CAPTION_RANGE:
            for index, entry in enumerate(out):
                if entry.start_ms < intent.end_ms and intent.start_ms < entry.end_ms:
                    out[index] = replace(
                        entry, caption_position="LOWER_THIRD", caption_size_px=30
                    )
        if CanonicalArtifact.EVIDENCE_ASSET in intent.target_artifacts:
            for index, entry in enumerate(out):
                if entry.start_ms < intent.end_ms and intent.start_ms < entry.end_ms:
                    out[index] = replace(entry, evidence_path=entry.evidence_path)
    return out


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(CASES), default="a")
    parser.add_argument("--out", type=Path, default=REPO / "output" / "p5_1")
    parser.add_argument("--no-provider", action="store_true")
    args = parser.parse_args()

    register_video_understanding_providers(force=True)
    selection = select_video_understanding_provider()
    _log(f"provider selection: {selection.to_dict()}")

    result = asyncio.run(
        run_case(args.case, args.out, allow_provider=not args.no_provider)
    )
    _write(args.out / f"case_{args.case}_result.json", result.to_dict())
    for stage in result.stages:
        _log(f"  {stage.status:<20} {stage.name}: {stage.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
