"""Optional ``raea check`` bypass for finished films.

Feature flag ``HEVI_RAEA_CHECK`` (default off).  When on, the internal QA
bypass shells out to a locally installed ``raea`` binary (``HEVI_RAEA_BIN`` or
``/opt/raea/bin/raea``), stores the P0-P3 findings in the task's QA metadata and
appends one item to the canvas review queue.  A missing binary, a timeout
(60 s default) or any process error is a skip, never a render failure: the film
has already been produced and delivered before this check runs.

Licence note: raea is FSL-1.1-ALv2.  Only the CLI binary at runtime is used,
only on internally produced files.  No raea source, binary, TSX/HTML editor or
rendering API is exposed to users, and nothing from raea is committed here.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RAEA_BIN = Path("/opt/raea/bin/raea")
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_DARK_LUMA = 42.0
_TRUE = {"1", "true", "yes", "on"}


def raea_check_enabled() -> bool:
    return os.environ.get("HEVI_RAEA_CHECK", "").strip().lower() in _TRUE


def raea_binary() -> str | None:
    configured = os.environ.get("HEVI_RAEA_BIN", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(DEFAULT_RAEA_BIN)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _summarise(issues: list[dict[str, Any]], passed: list[Any]) -> dict[str, Any]:
    by_level: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        level = str(issue.get("p") or issue.get("priority") or "?")
        rule = str(issue.get("rule") or "?")
        by_level[level] = by_level.get(level, 0) + 1
        by_rule[rule] = by_rule.get(rule, 0) + 1
    return {
        "total": len(issues),
        "by_level": dict(sorted(by_level.items())),
        "by_rule": dict(sorted(by_rule.items())),
        "passed": len(passed),
        "blocking": sum(by_level.get(level, 0) for level in ("P0", "P1")),
    }


def _mean_luma(video: Path, *, frames: int = 3) -> float | None:
    """Average 0-255 luma of a few frames; None when ffmpeg cannot read it."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video), "-vf", "scale=32:32,format=gray",
             "-frames:v", str(frames), "-f", "rawvideo", "-"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    data = proc.stdout
    return sum(data) / len(data)


def reclassify_dark_blotching(
    issues: list[dict[str, Any]], *, mean_luma: float | None, dark_luma: float = DEFAULT_DARK_LUMA
) -> tuple[list[dict[str, Any]], int]:
    """Downgrade ``blotching`` P1 findings on a dark master to P2 advisory.

    Deep shadows and cinematic grades trigger the blotching heuristic without a
    real defect (S13 measured this on 11/30 historical films).  The finding is
    kept, with the dark master recorded, and no longer counts as blocking.
    """
    if mean_luma is None or mean_luma >= dark_luma:
        return issues, 0
    changed = 0
    out = []
    for issue in issues:
        if not isinstance(issue, dict):
            out.append(issue)
            continue
        rule = str(issue.get("rule") or "").lower()
        level = str(issue.get("p") or issue.get("priority") or "")
        if "blotch" in rule and level in ("P1", "1"):
            issue = {**issue, "p": "P2", "priority": "P2",
                     "dark_scene_downgrade": True,
                     "note": f"深色母版（平均亮度 {mean_luma:.1f}）blotching 误报，降为 P2 提示"}
            changed += 1
        out.append(issue)
    return out, changed


def run_raea_check(video_path: str | Path, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Run ``raea check`` on one finished file; never raises."""
    evidence: dict[str, Any] = {
        "enabled": raea_check_enabled(),
        "checked": False,
        "status": "skipped",
        "file": str(video_path),
    }
    if not evidence["enabled"]:
        evidence["reason"] = "HEVI_RAEA_CHECK is off"
        return evidence
    binary = raea_binary()
    if binary is None:
        evidence["reason"] = "raea binary not found (HEVI_RAEA_BIN / /opt/raea/bin/raea)"
        return evidence
    video = Path(video_path)
    if not video.is_file() or video.stat().st_size == 0:
        evidence["reason"] = "missing or empty video"
        return evidence
    evidence["binary"] = binary
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="raea-check-") as tmp:
        out = Path(tmp) / "check.json"
        cmd = [binary, "check", str(video), "-o", str(out)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=max(1.0, float(timeout_s)), check=False
            )
        except subprocess.TimeoutExpired:
            evidence.update(
                {
                    "status": "timeout",
                    "reason": f"raea check exceeded {timeout_s:g}s",
                    "duration_s": round(time.monotonic() - started, 3),
                }
            )
            return evidence
        except (OSError, subprocess.SubprocessError) as exc:
            evidence.update(
                {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "duration_s": round(time.monotonic() - started, 3),
                }
            )
            return evidence
        evidence["duration_s"] = round(time.monotonic() - started, 3)
        evidence["exit_code"] = int(proc.returncode or 0)
        raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        evidence["output_excerpt"] = raw[-4000:]
        payload: dict[str, Any] | None = None
        if out.is_file():
            try:
                loaded = json.loads(out.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = None
        if payload is None:
            evidence["status"] = "ok" if proc.returncode == 0 else "error"
            evidence["reason"] = "raea check did not write parseable JSON"
            return evidence
        issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        passed = payload.get("passed") if isinstance(payload.get("passed"), list) else []
        luma = _mean_luma(video)
        issues, downgraded = reclassify_dark_blotching(issues, mean_luma=luma)
        evidence.update(
            {
                "status": "ok",
                "checked": True,
                "mean_luma": None if luma is None else round(luma, 2),
                "dark_blotching_downgraded": downgraded,
                "issues": issues[:60],
                "passed_checks": passed[:30],
                "summary": _summarise(issues, passed),
            }
        )
        # raea exits 1 when P0/P1 findings exist; that is a valid result.
        return evidence


def attach_to_quality(result: dict[str, Any], *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Run the check on a completed render and attach it to ``quality``."""
    if not raea_check_enabled():
        return result
    path = str(result.get("result_video_path") or "")
    quality = result.get("quality")
    if not path or not isinstance(quality, dict):
        return result
    check = run_raea_check(path, timeout_s=timeout_s)
    quality.setdefault("checks", {})["raea_check"] = check
    return result


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _thumbnails(video: Path, count: int = 3) -> list[str]:
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []
    try:
        duration = float(
            subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
                text=True, timeout=20, stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        duration = 5.0
    found: list[str] = []
    for index in range(count):
        target = video.parent / f".{video.stem}.qa{index + 1}.jpg"
        frac = (index + 1) / (count + 1)
        proc = subprocess.run(
            [ffmpeg, "-y", "-ss", f"{max(0.0, duration * frac):.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=480:-1", str(target)],
            capture_output=True, timeout=60, check=False,
        )
        if proc.returncode == 0 and target.is_file():
            found.append(str(target))
    return found


async def enqueue_task_review(
    pool: Any,
    *,
    task_id: str,
    line_id: str,
    video_path: str,
    check: dict[str, Any],
) -> str | None:
    """Append a production film to the canvas review queue (advisory only).

    Production tasks have no canvas graph, so a hidden QA graph row keyed by the
    task UUID is created first (the queue's foreign key needs one).  Every
    failure is swallowed: the queue must not affect delivery.
    """
    if pool is None:
        return None
    try:
        task_uuid = uuid.UUID(str(task_id))
    except (TypeError, ValueError):
        return None
    item_id = uuid.uuid4()
    node_key = str(line_id or "task")
    sentence = f"{line_id or 'task'} 成片质检（raea check）"
    video = Path(video_path)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO canvas_graphs (id, name, description, nodes_json, edges_json, "
                "user_id, created_at, updated_at) VALUES ($1,$2,$3,'[]'::jsonb,'[]'::jsonb,$4,$5,$5) "
                "ON CONFLICT (id) DO NOTHING",
                task_uuid,
                "S13 成片质检",
                "内部 raea check 旁路自动创建，仅用于审稿队列",
                "__s13_qa__",
                _now_naive(),
            )
            existing = await conn.fetchval(
                "SELECT id FROM canvas_review_queue WHERE graph_id=$1 AND node_id=$2 "
                "AND status IN ('pending','claimed') LIMIT 1",
                task_uuid,
                node_key,
            )
            if existing is not None:
                return str(existing)
            await conn.execute(
                "INSERT INTO canvas_review_queue "
                "(id, graph_id, node_id, node_type, sentence_text, thumbnails, offline_review, "
                "status, expires_at, created_at, updated_at) "
                "VALUES ($1,$2,$3,'video',$4,$5::jsonb,$6::jsonb,'pending',$7,$8,$8)",
                item_id,
                task_uuid,
                node_key,
                sentence,
                json.dumps(_thumbnails(video) if video.is_file() else [], ensure_ascii=False),
                json.dumps({"source": "raea_check", "raea_check": check}, ensure_ascii=False),
                _now_naive().replace(microsecond=0) + timedelta(hours=24),
                _now_naive(),
            )
    except Exception:
        logger.exception("raea check: canvas review enqueue failed for task %s", task_id)
        return None
    return str(item_id)


__all__ = [
    "DEFAULT_RAEA_BIN",
    "attach_to_quality",
    "enqueue_task_review",
    "raea_binary",
    "raea_check_enabled",
    "run_raea_check",
]
