"""Pairwise (A/B) judge with position swap."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from hevi.judge.backend import extract_json, select_backend
from hevi.judge.hard_checks import local_quality_score
from hevi.judge.types import PairwiseComparison, PairwiseJudgement


def compose_comparison(video_a, video_b, out_path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_a), "-i", str(video_b),
        "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", str(out_path),
    ]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0 or not out_path.is_file():
        cmd2 = [
            "ffmpeg", "-y", "-i", str(video_a), "-i", str(video_b),
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", str(out_path),
        ]
        cp2 = subprocess.run(cmd2, capture_output=True, text=True)
        if cp2.returncode != 0 or not out_path.is_file():
            raise RuntimeError(f"compose failed: {cp.stderr[-300:]}")
    return out_path


PAIRWISE_PROMPT = """You are comparing two versions of the same video. The clip contains two complete versions back to back. FIRST half is Candidate A, SECOND half is Candidate B. Judge only the video. Do not assume either is newer.

Compare on: hard_defects, narrative_clarity, visual_grounding, information_density, pacing, caption_readability, overall_watchability. Hard defects dominate.

Return ONLY JSON: {"winner": "A"|"B"|"TIE"|"INCOMPARABLE", "reason": "...", "improvements": ["actionable item for the loser"], "hard_defects": {"A": [...], "B": [...]}}"""


def _parse_judgement(text, raw) -> PairwiseJudgement:
    data = raw if isinstance(raw, dict) else extract_json(text)
    if not isinstance(data, dict):
        data = {}
    winner = str(data.get("winner", "TIE")).upper()
    if winner not in ("A", "B", "TIE", "INCOMPARABLE"):
        winner = "TIE"
    reason = str(data.get("reason", "") or data.get("rationale", "") or "")
    improvements = data.get("improvements")
    if not isinstance(improvements, list):
        improvements = []
        for k in ("actionable_improvements", "suggestions"):
            if isinstance(data.get(k), list):
                improvements = data.get(k)
                break
    hard = data.get("hard_defects", {})
    if not isinstance(hard, dict):
        hard = {}
    return PairwiseJudgement(winner=winner, reason=reason, improvements=[str(x) for x in improvements],
                             hard_defects=hard, raw=data)


def run_once(backend, comparison_video, prompt=PAIRWISE_PROMPT) -> PairwiseJudgement:
    res = backend.run(str(comparison_video), prompt)
    return _parse_judgement(res.text, res.raw)


def _local_improvements(video_loser, video_winner, sa, sb, ra, rb):
    imps = []
    # hard findings
    for f in ra.findings:
        imps.append(f"{f.name}: {f.detail}")
    # metrics
    if rb.metrics.get("probe", {}).get("duration", 0) and ra.metrics.get("probe", {}).get("duration", 0):
        if abs(ra.metrics["probe"]["duration"] - (rb.metrics["probe"]["duration"])) > 1.0:
            imps.append("pacing: align duration with winner")
    # black frames
    try:
        from hevi.judge.hard_checks import _black_ratio
        if _black_ratio(video_loser) > _black_ratio(video_winner) + 0.01:
            imps.append("black frames: reduce dark shots")
    except Exception:
        pass
    # volume
    try:
        from hevi.judge.hard_checks import _mean_volume
        mv_l = _mean_volume(video_loser)
        mv_w = _mean_volume(video_winner)
        if mv_l is not None and mv_w is not None and mv_l < mv_w - 1.0:
            imps.append("audio: raise volume to match winner")
    except Exception:
        pass
    # repetition
    try:
        from hevi.judge.hard_checks import _repetition_ratio
        if _repetition_ratio(video_loser) > _repetition_ratio(video_winner) + 0.05:
            imps.append("visual: reduce repeated shots")
    except Exception:
        pass
    if not imps:
        imps.append("pacing: keep rhythm stable")
    # ensure adjust() can react
    if not any("pace" in i.lower() or "pacing" in i.lower() for i in imps):
        imps.append("pacing: minor rhythm polish")
    if not any("subtitle" in i.lower() or "caption" in i.lower() or "字幕" in i for i in imps):
        imps.append("subtitle: improve caption readability")
    return imps


def _run_local_pairwise(video_a, video_b, *, expected_duration_s=None, work_dir=None) -> PairwiseComparison:
    wd = Path(work_dir) if work_dir else Path(video_a).parent / "judge_tmp"
    wd.mkdir(parents=True, exist_ok=True)
    sa, ra, ia = local_quality_score(video_a, expected_duration_s)
    sb, rb, ib = local_quality_score(video_b, expected_duration_s)

    if sb < sa - 1e-9:
        winner = "B"
    elif sa < sb - 1e-9:
        winner = "A"
    else:
        winner = "TIE"

    reason = f"local metrics: A={sa:.3f} B={sb:.3f}"
    hard = {"A": [f.name for f in ra.findings], "B": [f.name for f in rb.findings]}
    imps = _local_improvements(video_a, video_b, sa, sb, ra, rb) if winner == "B" else \
           _local_improvements(video_b, video_a, sb, sa, rb, ra) if winner == "A" else \
           ["pacing: keep rhythm stable", "subtitle: improve caption readability"]

    j_fwd = PairwiseJudgement(winner=winner, reason=reason, improvements=imps, hard_defects=hard, raw={"A": sa, "B": sb})

    # swapped view: B first
    sb2, rb2, _ = local_quality_score(video_b, expected_duration_s)
    sa2, ra2, _ = local_quality_score(video_a, expected_duration_s)
    if sb2 < sa2 - 1e-9:
        w2_raw = "A"  # B (first) wins
    elif sa2 < sb2 - 1e-9:
        w2_raw = "B"
    else:
        w2_raw = "TIE"
    # map back: first half in swapped is original B
    if w2_raw == "A":
        mapped = "B"
    elif w2_raw == "B":
        mapped = "A"
    else:
        mapped = "TIE"

    if winner == "A" and mapped == "A":
        final = "A"
        consistent = True
    elif winner == "B" and mapped == "B":
        final = "B"
        consistent = True
    elif winner == "TIE" and mapped == "TIE":
        final = "TIE"
        consistent = True
    else:
        final = "TIE"
        consistent = False

    j_swp = PairwiseJudgement(winner=w2_raw, reason=reason, improvements=imps, hard_defects={"A": [f.name for f in rb.findings], "B": [f.name for f in ra.findings]}, raw={"A": sb, "B": sa})
    return PairwiseComparison(video_a=str(video_a), video_b=str(video_b),
                             run_forward=j_fwd, run_swapped=j_swp, winner=final,
                             consistent=consistent, reason=reason)


def run_pairwise(backend, video_a, video_b, *, work_dir=None, prompt=PAIRWISE_PROMPT, expected_duration_s=None) -> PairwiseComparison:
    if getattr(backend, "name", None) == "local":
        return _run_local_pairwise(video_a, video_b, expected_duration_s=expected_duration_s, work_dir=work_dir)
    wd = Path(work_dir) if work_dir else Path(video_a).parent / "judge_tmp"
    wd.mkdir(parents=True, exist_ok=True)
    fwd_path = wd / "cmp_forward.mp4"
    swp_path = wd / "cmp_swapped.mp4"
    compose_comparison(video_a, video_b, fwd_path)
    compose_comparison(video_b, video_a, swp_path)

    j_fwd = run_once(backend, fwd_path, prompt)
    j_swp = run_once(backend, swp_path, prompt)

    mapped_swp_winner = j_swp.winner
    if mapped_swp_winner == "A":
        mapped_swp_winner = "B"
    elif mapped_swp_winner == "B":
        mapped_swp_winner = "A"

    if j_fwd.winner == "A" and mapped_swp_winner == "A":
        final = "A"
        consistent = True
    elif j_fwd.winner == "B" and mapped_swp_winner == "B":
        final = "B"
        consistent = True
    else:
        final = "TIE"
        consistent = (j_fwd.winner == mapped_swp_winner)
    reason = j_fwd.reason or j_swp.reason
    return PairwiseComparison(video_a=str(video_a), video_b=str(video_b),
                             run_forward=j_fwd, run_swapped=j_swp, winner=final,
                             consistent=consistent, reason=reason)
