"""Reference video breakdown (omodul transaction): video -> breakdown.json + contactsheet + markdown."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.omodul_impl._media import (
    _detect_silences,
    _extract_frames,
    _probe_video,
    _sha256,
    _transcribe_audio_with_whisper,
)
from hevi.layer4_legacy.viralclone.oprim_impl.specs import (
    ReferenceBreakdown,
    WordToken,
)
from hevi.layer4_legacy.viralclone.oskill_impl.breakdown_math import (
    classify_sentence_semantic_role,
    compute_rhythm_stats,
    detect_subtitle_box_from_frames,
)
from hevi.video_intelligence.boundaries import ShotBoundaryDetector
from hevi.video_intelligence.contactsheet import build_contact_sheet
from hevi.video_intelligence.models import VideoProbe

_enabled_pillars = {"report", "cost", "decision_trail"}


def _render_breakdown_markdown(breakdown: ReferenceBreakdown) -> str:
    r = breakdown.rhythm
    sub = breakdown.subtitle_box
    lines = [
        f"# Reference Video Breakdown Card: {Path(breakdown.source_video).name}",
        "",
        "## 1. Video Profile",
        f"- Resolution: {breakdown.width}x{breakdown.height} ({round(breakdown.width / max(1, breakdown.height), 2)})",
        f"- Duration: {breakdown.duration_s:.2f}s",
        f"- FPS: {breakdown.fps}",
        f"- SHA256: `{breakdown.provenance.get('sha256', '')[:16]}...`",
        "",
        "## 2. Rhythm & Hook Analysis",
        f"- **First Shot (Hook Visual)**: {r.first_shot_duration_s:.2f}s",
        f"- **Hook Timing (First Spoken Sentence)**: {r.hook_duration_s:.2f}s",
        f"- **Shot Count**: {r.shot_count}",
        f"- **Average Shot Duration**: {r.mean_shot_duration_s:.2f}s (Median: {r.median_shot_duration_s:.2f}s)",
        f"- **Cut Frequency**: {r.cuts_per_minute:.1f} cuts/min",
        f"- **Speech Rate**: {r.speech_rate_wps:.1f} chars/sec",
        f"- **Silence Periods**: {len(r.silence_intervals)} detected",
        "",
        "## 3. Subtitle Box Detection",
    ]
    if sub:
        lines.extend(
            [
                f"- Bounding Box: ({sub.x0}, {sub.y0}) -> ({sub.x1}, {sub.y1})",
                f"- Line Height: {sub.line_height_px}px ({sub.relative_line_height * 100:.1f}% of frame height)",
                f"- Average Y: {sub.avg_y_px}px",
                f"- Sample Text Detected: \"{sub.text_sample}\"",
            ]
        )
    else:
        lines.append("- Subtitle Box: Not detected or clean footage")

    lines.extend(
        [
            "",
            "## 4. Spoken Sentences & Semantic Role Breakdown",
        ]
    )
    for sent in breakdown.sentences:
        idx = sent.get("index", 0)
        role = sent.get("role", "selling_point")
        text = sent.get("text", "")
        start = sent.get("start_s", 0.0)
        end = sent.get("end_s", 0.0)
        lines.append(f"- **[{role.upper()}]** `[{start:.2f}s - {end:.2f}s]`: {text}")

    lines.extend(
        [
            "",
            "## 5. Visual Semantic Audit",
            f"- Semantic Visual Category: `{breakdown.semantic_visual}` (No local vision model loaded; no forged tags)",
            "",
            "## 6. Structural Advice for Viral Template",
            f"- Maintain visual hook cut before {min(3.0, r.first_shot_duration_s):.1f}s.",
            f"- Keep speech cadence around {r.speech_rate_wps:.1f} chars/sec.",
            f"- Reserve lower {sub.relative_line_height * 100 if sub else 12:.1f}% for high-contrast animated subtitles.",
        ]
    )
    return "\n".join(lines) + "\n"


def reference_breakdown(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Execute clean-room reference video breakdown transaction."""
    t0 = time.time()
    trail: list[dict[str, Any]] = []
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)

    video_path = input_data.get("video_path") or input_data.get("source_video")
    if not video_path or not Path(video_path).is_file():
        return {
            "status": "blocked",
            "reason": f"INVALID_SOURCE_VIDEO: {video_path}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": [{"step": "validate_input", "error": "file_not_found"}],
            "report": {},
        }

    vpath = Path(video_path)
    trail.append({"step": "validate_input", "status": "ok", "path": str(vpath)})

    try:
        # 1. Probe & checksum
        probe = _probe_video(vpath)
        sha = _sha256(vpath)
        trail.append({"step": "probe_video", "probe": probe, "sha256": sha})

        # 2. Shot cut boundaries
        vprobe = VideoProbe(
            asset_id=f"asset_{vpath.stem}",
            path=str(vpath),
            duration_ms=int(round(probe["duration_s"] * 1000)),
            width=probe["width"],
            height=probe["height"],
            fps_num=int(round(probe["fps"] * 1000)),
            fps_den=1000,
            has_video=True,
            has_audio=bool(probe.get("has_audio")),
        )
        detector = ShotBoundaryDetector(threshold=0.32, minimum_shot_duration_ms=500)
        evidence = detector.detect(str(vpath), vprobe)
        cut_timestamps_s = [round(item.timestamp_ms / 1000.0, 3) for item in evidence]
        trail.append({"step": "detect_cuts", "cut_count": len(cut_timestamps_s), "cuts_s": cut_timestamps_s})

        # 3. Audio transcription & word timestamps
        words_raw, sents_raw = _transcribe_audio_with_whisper(vpath)
        words: list[WordToken] = [
            WordToken(word=w["word"], start_s=w["start_s"], end_s=w["end_s"], score=w["score"])
            for w in words_raw
        ]
        trail.append({"step": "transcribe_whisper", "word_count": len(words), "sentence_count": len(sents_raw)})

        # 4. Audio silences & rhythm stats
        silences = _detect_silences(vpath) if probe["has_audio"] else []
        rhythm = compute_rhythm_stats(probe["duration_s"], cut_timestamps_s, words, sents_raw, silences)
        trail.append({"step": "compute_rhythm", "stats": rhythm.to_dict()})

        # 5. Extract sample frames for OCR & Contactsheet
        frames_dir = dest / "sample_frames"
        sample_frames = _extract_frames(vpath, frames_dir, fps=1.0, max_frames=25)

        # 6. Subtitle box detection
        import cv2

        cv_frames = [cv2.imread(str(p)) for p in sample_frames if p.is_file()]
        subtitle_box = detect_subtitle_box_from_frames(cv_frames, probe["width"], probe["height"])
        trail.append({"step": "detect_subtitles", "box": subtitle_box.to_dict() if subtitle_box else None})

        # 7. Semantic categorization of sentences
        sents_with_roles: list[dict[str, Any]] = []
        role_map: dict[str, list[str]] = {"hook": [], "selling_points": [], "proof": [], "cta": []}
        for s in sents_raw:
            role = classify_sentence_semantic_role(s["text"], s["index"], len(sents_raw))
            s_dict = {**s, "role": role}
            sents_with_roles.append(s_dict)
            if role == "hook":
                role_map["hook"].append(s["text"])
            elif role == "cta":
                role_map["cta"].append(s["text"])
            elif role == "proof":
                role_map["proof"].append(s["text"])
            else:
                role_map["selling_points"].append(s["text"])
        trail.append({"step": "classify_semantics", "roles": role_map})

        # 8. Build Word-Annotated Contact Sheet
        # Map each sample frame's timestamp to spoken words
        sheet_timestamps: list[int] = []
        sheet_words: list[str] = []
        for idx, _ in enumerate(sample_frames):
            ts_s = float(idx)  # approx 1 fps
            ts_ms = int(round(ts_s * 1000))
            sheet_timestamps.append(ts_ms)
            # Find word spoken at ts_s
            active_words = [w.word for w in words if w.start_s <= ts_s <= w.end_s + 0.3]
            sheet_words.append(" ".join(active_words) if active_words else "")

        contact_sheet_path = dest / "contactsheet.jpg"
        build_contact_sheet(
            sample_frames,
            contact_sheet_path,
            columns=5,
            timestamps_ms=sheet_timestamps,
            words=sheet_words,
        )
        trail.append({"step": "build_contact_sheet", "path": str(contact_sheet_path)})

        # 9. Reference Breakdown Model & JSON / MD
        breakdown = ReferenceBreakdown(
            source_video=str(vpath),
            width=probe["width"],
            height=probe["height"],
            fps=probe["fps"],
            duration_s=probe["duration_s"],
            cut_timestamps_s=cut_timestamps_s,
            words=words,
            sentences=sents_with_roles,
            rhythm=rhythm,
            subtitle_box=subtitle_box,
            semantic_roles=role_map,
            semantic_visual="UNKNOWN",
            provenance={
                "sha256": sha,
                "timestamp": time.time(),
                "engine": "viralclone_breakdown_3o",
                "device": "cpu",
            },
        )

        breakdown_json_path = dest / "breakdown.json"
        breakdown_json_path.write_text(
            json.dumps(breakdown.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        breakdown_md_path = dest / "breakdown.md"
        breakdown_md_path.write_text(_render_breakdown_markdown(breakdown), encoding="utf-8")

        elapsed = time.time() - t0
        report = {
            "breakdown_json": str(breakdown_json_path),
            "breakdown_md": str(breakdown_md_path),
            "contact_sheet": str(contact_sheet_path),
            "shot_count": rhythm.shot_count,
            "duration_s": breakdown.duration_s,
            "hook_duration_s": rhythm.hook_duration_s,
            "cuts_per_minute": rhythm.cuts_per_minute,
            "subtitle_box_detected": bool(subtitle_box),
            "elapsed_s": round(elapsed, 2),
        }

        return {
            "status": "succeeded",
            "report": report,
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
        }

    except Exception as exc:
        trail.append({"step": "exception", "error": str(exc)})
        return {
            "status": "failed",
            "reason": f"BREAKDOWN_FAILED: {exc}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
            "report": {},
        }
