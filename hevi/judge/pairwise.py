"""Pairwise (A/B) judge with position swap."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from hevi.judge.backend import extract_json, select_backend
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


def run_pairwise(backend, video_a, video_b, *, work_dir=None, prompt=PAIRWISE_PROMPT) -> PairwiseComparison:
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
