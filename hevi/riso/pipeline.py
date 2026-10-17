"""Three-gate RISO production pipeline (分镜表 -> 样帧总览质检 -> 成片).

Gate 1: Storyboard (分镜表 + 落选段处理)
Gate 2: Keyframe Proof Sheet & QA (末帧总览图 + 6项自动化质检)
Gate 3: Final MP4 Render (30fps 1080x1920 + PSNR逐像素一致性校验)
Also provides direct_render() for one-click production with zero QA skipped.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import compute_sha256
from hevi.riso.gatekeeper import validate_screen_content
from hevi.riso.proof_sheet import create_proof_sheet
from hevi.riso.qa import QAReport, run_qa_checks
from hevi.riso.render import (
    WebRenderSession,
    check_disk_space,
    compute_image_psnr,
    extract_video_last_frame,
    render_clip,
)
from hevi.riso.storyboard import StoryboardPlan, generate_storyboard


class PipelineGateError(RuntimeError):
    """Raised when any confirmation gate fails."""


def run_gate1_storyboard(
    script_or_srt: str,
    out_dir: Path | str,
    title: str = "复利前三年分镜方案",
) -> StoryboardPlan:
    """Gate 1: Generate storyboard plan and validate subsequence content rules."""
    check_disk_space()
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    plan = generate_storyboard(script_or_srt, title=title)

    # Validate gatekeeper rules for each shot
    for shot in plan.shots:
        res = validate_screen_content(shot.template, shot.screen_data, shot.source_sentence)
        if not res.passed:
            raise PipelineGateError(
                f"Gate 1 failed on shot {shot.clip_id}: {'; '.join(res.errors)}"
            )

    # Save storyboard json
    sb_json = out_path / "storyboard.json"
    sb_json.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    return plan


def run_gate2_keyframes_and_qa(
    plan: StoryboardPlan,
    out_dir: Path | str,
    seed: int = 42,
) -> tuple[Path, list[QAReport]]:
    """Gate 2: Render end keyframes, stitch overview proof sheet, run automated QA."""
    check_disk_space()
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    keyframe_meta = []
    qa_reports: list[QAReport] = []

    for shot in plan.shots:
        # Render HTML and keyframe
        render_res = render_clip(
            template_name=shot.template,
            data=shot.screen_data,
            out_dir=out_path / "clips",
            clip_id=shot.clip_id,
            duration_s=shot.duration_s,
            palette_key=shot.palette,
            seed=seed,
            render_video=False,  # Keyframe only in Gate 2
        )

        keyframe_png = render_res["keyframe_png"]
        keyframe_meta.append({
            "keyframe_png": keyframe_png,
            "clip_id": shot.clip_id,
            "template": shot.template,
            "duration": shot.duration_s,
            "palette": shot.palette,
        })

        # Run automated QA battery
        qa_rep = run_qa_checks(
            clip_id=shot.clip_id,
            template=shot.template,
            data=shot.screen_data,
            source_sentence=shot.source_sentence,
            palette_name=shot.palette,
            keyframe_path=keyframe_png,
        )
        qa_reports.append(qa_rep)

        if not qa_rep.passed:
            failed_checks = [c.name for c in qa_rep.checks if not c.passed]
            raise PipelineGateError(
                f"Gate 2 QA failed on shot {shot.clip_id}: {failed_checks}"
            )

    # Stitch into overview proof sheet
    overview_png = out_path / "overview.png"
    create_proof_sheet(keyframe_meta, overview_png, title=f"RISO PROOF SHEET // {plan.title}")

    # Save QA report
    qa_json = out_path / "qa_report.json"
    qa_data = [r.to_dict() for r in qa_reports]
    qa_json.write_text(json.dumps(qa_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return overview_png, qa_reports


def run_gate3_final_render(
    plan: StoryboardPlan,
    out_dir: Path | str,
    seed: int = 42,
    alpha: bool = False,
) -> dict[str, Any]:
    """Gate 3: Render final 30fps MP4s and verify last-frame PSNR >= 45 dB."""
    check_disk_space()
    out_path = Path(out_dir).resolve()
    clips_dir = out_path / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = []

    for shot in plan.shots:
        render_res = render_clip(
            template_name=shot.template,
            data=shot.screen_data,
            out_dir=clips_dir,
            clip_id=shot.clip_id,
            duration_s=shot.duration_s,
            palette_key=shot.palette,
            seed=seed,
            render_video=True,
            alpha=alpha,
        )

        mp4_path = render_res["mp4_path"]
        keyframe_png = render_res["keyframe_png"]
        psnr = render_res["psnr"]

        if psnr is not None and psnr < 45.0:
            raise PipelineGateError(
                f"Gate 3 PSNR verification failed on {shot.clip_id}: {psnr:.2f} dB < 45.0 dB threshold"
            )

        sha = compute_sha256(mp4_path)
        manifest_entries.append({
            "clip_id": shot.clip_id,
            "template": shot.template,
            "mp4_path": str(mp4_path),
            "keyframe_png": str(keyframe_png),
            "duration_s": shot.duration_s,
            "sha256": sha,
            "psnr": psnr,
        })

    manifest = {
        "title": plan.title,
        "clip_count": len(manifest_entries),
        "total_duration_s": sum(e["duration_s"] for e in manifest_entries),
        "clips": manifest_entries,
    }
    manifest_json = out_path / "manifest.json"
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return manifest


def direct_render(
    script_or_srt: str,
    out_dir: Path | str,
    title: str = "直接出片",
    seed: int = 42,
    alpha: bool = False,
) -> dict[str, Any]:
    """One-click execution of all 3 gates with complete QA verification."""
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # Gate 1
    plan = run_gate1_storyboard(script_or_srt, out_path, title=title)
    # Gate 2
    overview_png, qa_reports = run_gate2_keyframes_and_qa(plan, out_path, seed=seed)
    # Gate 3
    manifest = run_gate3_final_render(plan, out_path, seed=seed, alpha=alpha)

    return {
        "plan": plan.to_dict(),
        "overview_png": str(overview_png),
        "qa_reports": [r.to_dict() for r in qa_reports],
        "manifest": manifest,
    }
