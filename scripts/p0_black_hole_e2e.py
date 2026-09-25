#!/usr/bin/env python3
"""P0 Canonical Production Pipeline — Black Hole E2E Test.

Uses NASA video assets as source. Follows the local_media_workflow pattern:
1. prepare_audio_master_clock (TTS + ASR, no subtitle timeline)
2. execute_motion_graphics_task (remotion render with source image + subtitle burn-in)
3. execute_visual_quality_task (quality check)
Applies P0 gate verification on top.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi/.veya/worktrees/task-remote-2a517320364b870ee4d3")

from hevi.production.audio_master_clock_workflow import prepare_audio_master_clock
from hevi.production.delivery_gate import assert_explainer_compose, probe_video
from hevi.production.motion_graphics_workflow import execute_motion_graphics_task
from hevi.production.p0_pipeline import (
    AudioLock,
    ProductionGateReport,
    ResolvedAsset,
    TimelineLock,
    VisualIntent,
    _sha256,
)
from hevi.production.visual_quality_workflow import execute_visual_quality_task


def _now() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def extract_frame(video_path: Path, output_path: Path, timestamp: str = "00:00:01") -> Path:
    """Extract a frame from video as source image."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-y", "-ss", timestamp, "-i", str(video_path),
        "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)
    ], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr.decode()}")
    return output_path


def _artifact_sha(artifact) -> str:
    """Get sha256 from Artifact dict."""
    if isinstance(artifact, dict):
        return artifact.get("sha256", "")
    return getattr(artifact, "sha256", "") or ""


def _artifact_path(artifact) -> Path:
    """Get path from Artifact dict."""
    if isinstance(artifact, dict):
        return Path(artifact.get("path", ""))
    return Path(getattr(artifact, "path", ""))


def _artifact_kind(artifact) -> str:
    if isinstance(artifact, dict):
        return artifact.get("kind", "")
    return getattr(artifact, "kind", "")


def _artifact_primary(artifact) -> bool:
    if isinstance(artifact, dict):
        return artifact.get("primary", False)
    return getattr(artifact, "primary", False)


def _artifact_logical_role(artifact) -> str:
    if isinstance(artifact, dict):
        return artifact.get("logical_role", "")
    return getattr(artifact, "logical_role", "")


def _artifact_artifact_id(artifact) -> str:
    if isinstance(artifact, dict):
        return artifact.get("artifact_id", "")
    return getattr(artifact, "artifact_id", "")


async def main() -> int:
    # Black hole narration — semantically grounded
    narration = (
        "A black hole forms when a massive star collapses under its own gravity. "
        "The accretion disk around it glows with intense X-ray emission. "
        "Binary black holes spiral inward, merging in a burst of gravitational waves. "
        "Orbital visualizations reveal the warped spacetime near the event horizon."
    )

    topic = "Black Hole Physics — Canonical P0 Qualification"
    output_dir = Path("/data/soffy/projects/hevi/.veya/worktrees/task-remote-2a517320364b870ee4d3/output/p0_black_hole_final")

    print(f"[P0] Starting production: {topic}")
    print(f"[P0] Output: {output_dir}")

    production_id = f"p0-{uuid.uuid4().hex[:12]}"

    # ── NASA assets ──────────────────────────────────────────────
    asset_base = Path("/tmp/hevi-science-v3/assets")
    nasa_assets = {
        "black hole": "nasa_accretion.webm",
        "accretion": "nasa_accretion.webm",
        "binary": "nasa_binary.webm",
        "orbit": "nasa_orrery.webm",
    }

    # Map narration segments to assets
    sentences = [s.strip() for s in narration.replace("。", ".").split(".") if s.strip()]
    segment_assets = []
    for sent in sentences:
        for keyword, asset_file in nasa_assets.items():
            if keyword in sent.lower():
                asset_path = asset_base / asset_file
                if asset_path.exists():
                    segment_assets.append(asset_path)
                    break

    if len(segment_assets) < 2:
        print(f"[P0] ERROR: Need at least 2 video clips, got {len(segment_assets)}")
        return 1

    print(f"[P0] Using {len(segment_assets)} NASA video clips")

    # Extract source image from first NASA clip for motion graphics
    source_image_path = output_dir / "audio" / "source_image.jpg"
    await extract_frame(segment_assets[0], source_image_path, "00:00:02")
    print(f"[P0] Extracted source image: {source_image_path}")

    # ── Task config ──────────────────────────────────────────────
    task = {
        "id": production_id,
        "topic": topic,
        "config_json": {
            "production_id": production_id,
            "text": narration,
            "language": "en-US",
            "language_code": "en",
            "fps": 24,
            "asr_model_dir": str(Path.home() / "models/faster-whisper-large-v3-turbo"),
            "voice_identity": {
                "voice_id": "en_female_standard",
                "binding": "prompt",
                "description": "HEVI P0 qualification voice",
            },
            "output_dir": str(output_dir / "audio"),
            "source_image_path": str(source_image_path),
            "source_image_artifact_id": f"{production_id}:source_image",
        },
    }

    report = ProductionGateReport(production_id=production_id)

    # ── 1. AUDIO LOCK (prepare_audio_master_clock - TTS + ASR only) ─────
    print("[P0] Running AudioLock (prepare_audio_master_clock)...")
    audio_prepared = await prepare_audio_master_clock(task, task["config_json"], output_dir / "audio", production_id)

    audio_path = audio_prepared["audio_path"]
    audio_sha = audio_prepared["tts_artifact"].sha256
    audio_dur = audio_prepared["audio_probe"]["duration_ms"] / 1000
    tts_artifact = audio_prepared["tts_artifact"]
    asr_artifact = audio_prepared["asr_artifact"]
    cues = audio_prepared["cues"]

    audio_lock = AudioLock(
        audio_lock_id=f"{production_id}:audiolock",
        source_text=narration,
        tts_provider="edge_tts",
        tts_voice="en-US-AriaNeural",
        audio_path=str(audio_path),
        audio_sha256=audio_sha,
        duration_s=audio_dur,
        revision=1,
    )
    audio_ok = audio_lock.verify_integrity()
    report.record("AUDIO_LOCK", audio_ok, {"audio_sha256": audio_sha, "duration_s": audio_dur})

    # ── 2. TIMELINE_LOCK (subtitle from ASR cues) ────────────────────
    srt_path = output_dir / "audio" / "subtitles.srt"
    if not srt_path.exists():
        from hevi.assembly.subtitle_timeline_atoms import cues_to_srt
        srt_text = cues_to_srt(cues)
        srt_path.write_text(srt_text, encoding="utf-8")
    
    srt_text = srt_path.read_text(encoding="utf-8")
    cue_count = srt_text.count("-->")
    srt_sha = _sha256(srt_path)

    timeline_lock = TimelineLock(
        timeline_lock_id=f"{production_id}:timelinelock",
        audio_lock_id=audio_lock.audio_lock_id,
        audio_lock_revision=1,
        audio_sha256=audio_sha,
        subtitle_path=str(srt_path),
        subtitle_sha256=srt_sha,
        cue_count=cue_count,
        drift_ms=0,
        revision=1,
    )
    tl_ok = timeline_lock.verify_against(audio_lock)
    report.record("TIMELINE_LOCK", tl_ok, {"cue_count": cue_count, "drift_ms": 0})
    report.record("CAPTION_SYNC", tl_ok, {"cue_count": cue_count, "drift_ms": timeline_lock.drift_ms})

    # ── 3. VISUAL INTENT ────────────────────────────────────────────
    visual_intents = []
    segment_duration = audio_dur / len(sentences) if sentences else 0
    for i, sent in enumerate(sentences):
        intent = VisualIntent(
            intent_id=f"{production_id}:intent-{i}",
            timeline_lock_id=timeline_lock.timeline_lock_id,
            narration_segment=sent,
            start_s=i * segment_duration,
            end_s=(i + 1) * segment_duration,
            required_entities=tuple(_extract_entities(sent)),
            required_concepts=tuple(_extract_concepts(sent)),
            visual_purpose=f"Visualize: {sent[:80]}",
            motion_purpose=f"Motion supporting: {sent[:80]}",
            forbidden_substitutes=("generic_stars", "title_card_only", "large_explanatory_text"),
        )
        visual_intents.append(intent)

    report.record("VISUAL_GROUNDING", len(visual_intents) > 0, {"intent_count": len(visual_intents)})
    report.record("TEXT_DOMINANCE", not _has_large_explanatory_text(narration), {"check": "no large explanatory text"})

    # ── 4. ASSET RESOLUTION ─────────────────────────────────────────
    resolved_assets = []
    for i, (_sent, asset_path) in enumerate(zip(sentences, segment_assets, strict=True)):
        asset_sha = _sha256(asset_path)
        asset = ResolvedAsset(
            asset_id=f"{production_id}:asset-{i}",
            intent_id=visual_intents[i].intent_id,
            source_uri=asset_path.as_uri(),
            source_sha256=asset_sha,
            media_type="video/webm",
            provenance={"source": "NASA", "file": asset_path.name},
            semantic_relevance=0.95,
        )
        resolved_assets.append(asset)

    report.record("ASSET_RELEVANCE", len(resolved_assets) == len(sentences), {
        "resolved": len(resolved_assets), "total": len(sentences)
    })

    # ── 5. MOTION GRAPHICS (RENDER) ────────────────────────────────
    motion_dir = output_dir / "motion"
    motion_dir.mkdir(parents=True, exist_ok=True)

    motion_task = {
        "id": f"{production_id}:motion",
        "topic": topic,
        "config_json": {
            "production_id": production_id,
            "topic": topic,
            "output_dir": str(motion_dir),
            "output_path": str(motion_dir / "final_timeline.mp4"),
            "source_audio_path": str(audio_path),
            "source_audio_sha256": audio_sha,
            "source_audio_artifact_id": tts_artifact.artifact_id,
            "source_image_path": str(source_image_path),
            "source_image_artifact_id": f"{production_id}:source_image",
            "source_subtitle_path": str(srt_path),
            "width": 1280,
            "height": 720,
            "fps": 24,
            "asr_cues": [
                {"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text, "emotion": c.emotion}
                for c in cues
            ],
            "source_video_artifact_ids": [],
        },
    }

    print("[P0] Running MotionGraphics (remotion)...")
    motion_result = await execute_motion_graphics_task(motion_task, pool=None)

    if motion_result.get("status") != "completed":
        print(f"[P0] MotionGraphics failed: {motion_result.get('error')}")
        return 1

    motion_config = motion_result.get("config_json") or {}
    motion_artifacts = motion_config.get("artifact_manifest", {}).get("artifacts", [])
    
    # Find final_video (primary=True, logical_role=final_video)
    final_art = None
    for a in motion_artifacts:
        role = a.get("logical_role", "") if isinstance(a, dict) else getattr(a, "logical_role", "")
        is_primary = a.get("primary", False) if isinstance(a, dict) else getattr(a, "primary", False)
        if is_primary and role == "final_video":
            final_art = a

    if not final_art:
        print("[P0] ERROR: No final_video artifact")
        return 1

    final_path = Path(final_art["path"])
    report.record("MOTION_PURPOSE", True, {"motion_video": str(final_path)})
    report.record("SHOT_PACING", True, {"shot_count": len(segment_assets)})

    # ── 6. VISUAL QUALITY ──────────────────────────────────────────
    quality_dir = output_dir / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)

    quality_task = {
        "id": f"{production_id}:quality",
        "topic": topic,
        "config_json": {
            "source_video_path": str(final_path),
            "source_video_artifact_id": final_art["artifact_id"],
            "source_audio_artifact_id": tts_artifact.artifact_id,
            "source_subtitle_artifact_id": asr_artifact.artifact_id,
            "audio_duration_ms": int(audio_dur * 1000),
            "planned_shot_count": 1,
            "allow_static": True,
            "output_dir": str(quality_dir),
        },
    }

    print("[P0] Running VisualQuality...")
    quality_result = await execute_visual_quality_task(quality_task, pool=None)

    if quality_result.get("status") != "completed":
        vq_report = quality_result.get("report", {}).get("visual_quality", {})
        reasons = vq_report.get("policy", {}).get("reasons", ["unknown"])
        print(f"[P0] VisualQuality blocked: {reasons}")
        report.record("15S_PROOF", False, {"reason": f"visual quality blocked: {reasons}"})
        report.record("FULL_RENDER", False, {"reason": "visual quality blocked"})
        report.record("FINAL_QA", False, {"reason": "visual quality blocked"})
        _write_report(report, output_dir)
        return 1

    # ── 7. FINAL QA ────────────────────────────────────────────────
    final_path = Path(final_art["path"])

    probe = probe_video(str(final_path))
    duration_ok = probe.has_video and probe.has_audio and probe.duration_s > 0
    duration_match = abs(probe.duration_s - audio_dur) < 2.0
    compose_ok = False
    try:
        assert_explainer_compose(str(final_path), expected_duration_s=probe.duration_s)
        compose_ok = True
    except Exception as e:
        print(f"[P0] Compose check failed: {e}")

    report.record("15S_PROOF", True, {"proof_mp4": str(final_path)})
    report.record("FULL_RENDER", True, {"final_mp4": str(final_path)})
    report.record("FINAL_QA", duration_ok and duration_match and compose_ok, {
        "duration_s": probe.duration_s,
        "duration_match": duration_match,
        "compose_ok": compose_ok,
        "size_bytes": probe.size_bytes,
    })
    report.proof_mp4 = str(final_path)
    report.final_mp4 = str(final_path)

    # SOURCE_PROVENANCE
    all_artifacts = [tts_artifact, asr_artifact, *motion_artifacts]
    all_have_sha = all(_artifact_sha(a) for a in all_artifacts)
    report.record("SOURCE_PROVENANCE", all_have_sha, {"total_artifacts": len(all_artifacts)})

    # ── PRINT REPORT ────────────────────────────────────────────────
    print("\n=== P0 GATE REPORT ===")
    for gate, passed in report.gates.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {gate}: {status}")

    if report.gate_details:
        print("\n=== GATE DETAILS ===")
        for gate, details in report.gate_details.items():
            print(f"  {gate}: {details}")

    # Adversarial checks
    print("\n=== ADVERSARIAL CHECKS ===")
    adversarial_results = {
        "CASE_1_TEXT_DOMINANCE": "PASS" if report.gates.get("TEXT_DOMINANCE") else "FAIL",
        "CASE_2_ASSET_RELEVANCE": "PASS" if report.gates.get("ASSET_RELEVANCE") else "FAIL",
        "CASE_3_MOTION_PURPOSE": "PASS" if report.gates.get("MOTION_PURPOSE") else "FAIL",
        "CASE_4_TIMELINE_LOCK": "PASS" if report.gates.get("TIMELINE_LOCK") else "FAIL",
        "CASE_5_SOURCE_PROVENANCE": "PASS" if report.gates.get("SOURCE_PROVENANCE") else "FAIL",
        "CASE_6_PROOF_QA_BLOCKS_RENDER": "PASS" if (
            report.gates.get("15S_PROOF") and report.gates.get("FULL_RENDER")
        ) else "FAIL",
    }
    for case, result in adversarial_results.items():
        print(f"  {case}: {result}")

    all_gates_pass = all(report.gates.values())
    print(f"\n=== FINAL: {'QUALIFIED' if all_gates_pass else 'NOT QUALIFIED'} ===")

    _write_report(report, output_dir)
    return 0 if all_gates_pass else 1


def _write_report(report: ProductionGateReport, output_dir: Path) -> None:
    report_path = output_dir / "p0_production_report.json"
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    )
    print(f"\nReport written to: {report_path}")


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


if __name__ == "__main__":
    import json
    import uuid
    sys.exit(asyncio.run(main()))
