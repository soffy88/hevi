"""Anidoodle's own gate and export verification, absorbed as Hevi QA nodes.

The engine's gate checks determinism, the pure-function contract, dead air and
the self-contained HTML artifact.  ``verify-export`` checks the delivered file:
frame count, duration, audio presence and the first frame.  Both print a
human-readable report, so this module parses the verdicts and keeps the raw
tail for the reviewer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .engine import AnidoodleError, film_meta, run_node

# S26 vertical safe area on a 1080x1920 canvas.  The left margin follows the
# S26 warm-gold profile (60 px); the other three are the brief's numbers.
SAFE_TOP = 150
SAFE_BOTTOM = 380
SAFE_RIGHT = 140
SAFE_LEFT = 60

_VERDICT = re.compile(r"(?:GATE|VERIFY-EXPORT):\s+(PASS|FAIL)\s+(\d+\s+of\s+\d+|\d+/\d+)")
_CHECK = re.compile(r"^\s+(PASS|FAIL|----)\s+(.+)$")


def _tail(text: str, limit: int = 4000) -> str:
    return (text or "")[-limit:]


def _parse(text: str) -> dict[str, Any]:
    verdict = _VERDICT.search(text or "")
    checks: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        match = _CHECK.match(line)
        if match:
            checks.append({"status": match.group(1), "detail": match.group(2).strip()})
    return {
        "verdict": verdict.group(1).lower() if verdict else "unknown",
        "passed_count": verdict.group(2) if verdict else "",
        "checks": checks,
        "failures": [row["detail"] for row in checks if row["status"] == "FAIL"],
    }


def run_gate(
    film: str,
    mp4: str | Path,
    *,
    drawing: bool = False,
    timeout: int = 1800,
) -> dict[str, Any]:
    path = Path(mp4).expanduser().resolve()
    if not path.is_file():
        raise AnidoodleError(f"gate needs an existing mp4: {path}")
    result = run_node(["tools/gate.mjs", film, "--mp4", str(path)], timeout=timeout)
    text = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    report = _parse(text)
    report.update(
        {
            "film": film,
            "mp4": str(path),
            "exit_code": result.returncode,
            "log_tail": _tail(text),
        }
    )
    if drawing:
        profile = _drawing_dead_air(film, path, timeout=timeout)
        report["drawing_profile"] = profile
        report["failures"] = [
            row
            for row in report["failures"]
            if "identical consecutive frames" not in row and "window under" not in row
        ]
        report["checks"] = [
            row
            for row in report["checks"]
            if "identical consecutive frames" not in row["detail"]
            and "window under" not in row["detail"]
        ]
        report["checks"].append(
            {
                "status": "PASS" if profile.get("pass") else "FAIL",
                "detail": "drawing profile: 1 s window under 0.02% changed"
                + ("" if profile.get("pass") else f"   windows {profile.get('windows')}"),
            }
        )
        if not profile.get("pass"):
            report["failures"].append("drawing profile dead air")
        report["dead_air_profile"] = "drawing"
        counted = [row for row in report["checks"] if row["status"] in ("PASS", "FAIL")]
        passed = [row for row in counted if row["status"] == "PASS"]
        report["passed_count"] = f"{len(passed)} of {len(counted)}"
    if drawing:
        report["ok"] = not report["failures"] and bool(
            report.get("drawing_profile", {}).get("pass")
        )
    else:
        report["ok"] = not report["failures"] and result.returncode == 0
    report["verdict"] = "pass" if report["ok"] else "fail"
    return report


def _drawing_dead_air(film: str, mp4: Path, *, timeout: int = 1800) -> dict[str, Any]:
    engine = Path(__file__).resolve().parents[2] / "third_party" / "anidoodle" / "engine"
    script = Path(__file__).resolve().parent / "drawing_deadair.mjs"
    meta = film_meta(film)
    result = run_node(
        [str(script), json.dumps(meta, ensure_ascii=False), str(mp4)],
        cwd=engine,
        timeout=timeout,
        env={"HEVI_ANIDOODLE_ENGINE_ABS": str(engine)},
    )
    if result.returncode != 0:
        raise AnidoodleError(
            "drawing dead-air check failed: " + ((result.stderr or result.stdout or "")[-1200:])
        )
    return json.loads((result.stdout or "").strip())


def run_verify_export(mp4: str | Path, *, timeout: int = 600) -> dict[str, Any]:
    path = Path(mp4).expanduser().resolve()
    if not path.is_file():
        raise AnidoodleError(f"verify-export needs an existing mp4: {path}")
    tool = (
        Path(__file__).resolve().parents[2]
        / "third_party"
        / "anidoodle"
        / "engine"
        / "tools"
        / "verify-export.mjs"
    )
    result = run_node([str(tool), str(path)], timeout=timeout)
    text = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    report = _parse(text)
    report.update(
        {
            "mp4": str(path),
            "exit_code": result.returncode,
            "ok": report["verdict"] == "pass" and result.returncode == 0,
            "log_tail": _tail(text),
        }
    )
    return report


def check_safe_area(
    boxes: Iterable[dict[str, float]],
    *,
    width: int,
    height: int,
    profile: str = "s26-vertical",
) -> dict[str, Any]:
    """Check declared text boxes against the S26 vertical safe area.

    ``boxes`` are ``{x0,y0,x1,y1}`` in canvas pixels.  This is enforced where a
    caller declares its text; anidoodle's plates do not report text boxes to the
    engine, so the gate reports "not_applicable" rather than inventing a pass.
    """

    rows = list(boxes)
    if not rows:
        return {
            "profile": profile,
            "ok": None,
            "status": "not_applicable",
            "reason": "no text boxes declared by the film",
            "safe": {
                "top": SAFE_TOP,
                "bottom": SAFE_BOTTOM,
                "right": SAFE_RIGHT,
                "left": SAFE_LEFT,
            },
        }
    allowed = {
        "x0": SAFE_LEFT,
        "y0": SAFE_TOP,
        "x1": width - SAFE_RIGHT,
        "y1": height - SAFE_BOTTOM,
    }
    failures: list[dict[str, Any]] = []
    for index, box in enumerate(rows):
        bad: list[str] = []
        if float(box.get("x0", 0)) < allowed["x0"]:
            bad.append("left")
        if float(box.get("y0", 0)) < allowed["y0"]:
            bad.append("top")
        if float(box.get("x1", width)) > allowed["x1"]:
            bad.append("right")
        if float(box.get("y1", height)) > allowed["y1"]:
            bad.append("bottom")
        if bad:
            failures.append({"index": index, "edges": bad, "box": box})
    return {
        "profile": profile,
        "ok": not failures,
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "safe": allowed,
    }
