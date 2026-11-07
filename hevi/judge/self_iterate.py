"""Self-iteration loop."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from hevi.judge.backend import select_backend
from hevi.judge.hard_checks import run_hard_checks
from hevi.judge.pairwise import run_pairwise
from hevi.judge.types import IterationRecord, SelfIterateResult


GenerateFn = Callable[[dict[str, Any], int, Path], Path]
AdjustFn = Callable[[dict[str, Any], list[str], str], dict[str, Any]]


def _default_adjust(params, improvements, line_id):
    p = dict(params)
    joined = " ".join(improvements).lower()
    if "pace" in joined or "pacing" in joined or "节奏" in joined:
        p["speed"] = min(1.2, float(p.get("speed", 1.0)) + 0.05)
    if "subtitle" in joined or "caption" in joined or "字幕" in joined:
        p["caption_size"] = int(p.get("caption_size", 48)) + 2
    if "black" in joined or "dark" in joined or "黑" in joined:
        p["grade"] = "bright"
    p.setdefault("iteration_note", joined[:200])
    return p


def run_self_iterate(
    line_id,
    generate,
    params,
    *,
    output_dir,
    backend=None,
    max_versions=3,
    adjust=None,
    pairwise_backend=None,
    expected_duration_s=None,
):
    if backend is None:
        backend = select_backend("mock")
    if pairwise_backend is None:
        pairwise_backend = backend
    if adjust is None:
        adjust = _default_adjust

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = SelfIterateResult(line_id=line_id)
    t0 = time.time()
    calls = 0

    current_params = dict(params)
    prev_video = None
    for version in range(1, max_versions + 1):
        vdir = out / f"v{version}"
        vdir.mkdir(parents=True, exist_ok=True)
        video = Path(generate(current_params, version, vdir))
        calls += 1

        hard = run_hard_checks(video, expected_duration_s=expected_duration_s)

        pairwise = None
        adopted = True
        if prev_video is not None:
            pairwise = run_pairwise(pairwise_backend, prev_video, video, work_dir=vdir / "cmp")
            calls += 2
            if pairwise.winner != "B":
                adopted = False

        changes = []
        if pairwise is not None:
            if adopted:
                changes = list(pairwise.run_forward.improvements)
            else:
                changes = [f"rejected: {pairwise.reason}"]

        rec = IterationRecord(
            version=version,
            video_path=str(video),
            hard_report=hard,
            pairwise_vs_prev=pairwise,
            adopted=adopted,
            changes=changes,
            params=dict(current_params),
        )
        result.versions.append(rec)

        if not adopted:
            break

        result.final_path = str(video)
        result.final_version = version
        prev_video = video

        if version < max_versions:
            improvements = []
            if pairwise is not None:
                improvements = pairwise.run_forward.improvements
            improvements = improvements + [f"{f.name}: {f.detail}" for f in hard.findings]
            current_params = adjust(current_params, improvements, line_id)

    result.total_calls = calls
    result.total_elapsed_s = time.time() - t0
    if not result.final_path and result.versions:
        result.final_path = result.versions[-1].video_path
        result.final_version = result.versions[-1].version
    return result


def generate_zeroline(line_id, params, output_dir):
    from hevi.layer4_legacy.zerolines import zero_line_workflow

    input_data = {"line_id": line_id}
    input_data.update({k: v for k, v in params.items() if k in ("texts", "queries", "topic", "title", "lang", "media_path", "offsets", "labels", "extras")})
    if "text" in params and "texts" not in input_data:
        input_data["texts"] = params["text"] if isinstance(params["text"], (list, tuple)) else [params["text"]]
    if "query" in params and "queries" not in input_data:
        input_data["queries"] = params["query"] if isinstance(params["query"], (list, tuple)) else [params["query"]]
    res = zero_line_workflow(None, input_data, output_dir)
    finals = res.get("finals") or []
    if not finals:
        raise RuntimeError(f"zeroline generation failed: {res.get('reason')}")
    return Path(finals[0])
