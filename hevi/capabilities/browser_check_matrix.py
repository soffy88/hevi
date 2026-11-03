"""Browser check matrix gate (``qa.browser_check_matrix``).

Clean-room rewrite of the *discipline* described in
``hevi-vs-open-3d-skills.md`` section 2.7 (site-check): a real
browser check runs Chromium and WebKit at three widths, follows
deep links, waits for a caller-supplied ready expression, and
fails the run (exit code 1) when any shot shows a page error, a
4xx/5xx response, a blank canvas, or horizontal overflow. What
was not checked must be stated plainly. This module judges check
*plans* and check *report schemas* only; it performs no browser
run itself (the executor is a later item, B2, and is not part of
this graft).

No author-reported number is used here: the matrix (two browsers,
three widths) is the required shape of a plan, not a performance
threshold, and the ready-wait value is caller-supplied. A missing
wait, a missing ready expression, or a missing list of unexamined
items fails the plan.

Failure contract: a malformed plan or report (not a JSON object,
missing required section) raises :class:`CapabilityError`. A
well-formed plan or report that violates the matrix returns
``verdict: "fail"`` with named issues; it never raises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

REQUIRED_BROWSERS = ("chromium", "webkit")
REQUIRED_WIDTHS = (1440, 768, 390)
REQUIRED_FAILURE_CONDITIONS = (
    "page_error",
    "http_4xx",
    "http_5xx",
    "blank_canvas",
    "horizontal_overflow",
)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_obj(value: Any) -> bool:
    return isinstance(value, dict)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_browser_check_plan(plan: Any) -> dict[str, Any]:
    """Judge one browser-check plan against the matrix."""
    if not _is_obj(plan):
        raise CapabilityError(
            "qa.browser_check_matrix: plan must be a JSON object"
        )
    matrix = plan.get("matrix")
    if not _is_obj(matrix):
        raise CapabilityError(
            "qa.browser_check_matrix: plan requires a 'matrix' object"
        )
    issues: list[dict[str, Any]] = []
    browsers = matrix.get("browsers")
    if not isinstance(browsers, list):
        issues.append(
            _issue(
                "browsers_missing",
                "matrix must list 'browsers' as a list containing "
                "chromium and webkit",
            )
        )
        browsers = []
    for name in REQUIRED_BROWSERS:
        if name not in browsers:
            issues.append(
                _issue(
                    "browser_missing",
                    f"matrix must include browser {name!r}; the matrix "
                    "is Chromium plus WebKit",
                    browser=name,
                )
            )
    widths = matrix.get("widths")
    if not isinstance(widths, list):
        issues.append(
            _issue(
                "widths_missing",
                "matrix must list 'widths' as a list containing 1440, "
                "768 and 390",
            )
        )
        widths = []
    for width in REQUIRED_WIDTHS:
        if width not in widths:
            issues.append(
                _issue(
                    "width_missing",
                    f"matrix must include width {width}; the matrix is "
                    "1440 / 768 / 390",
                    width=width,
                )
            )
    deep_links = matrix.get("deep_links")
    if not isinstance(deep_links, list) or not deep_links or not all(
        isinstance(link, str) and link.strip() for link in deep_links
    ):
        issues.append(
            _issue(
                "deep_links_missing",
                "matrix must list a non-empty 'deep_links' list of "
                "URLs to check at every width",
            )
        )
    ready = matrix.get("ready")
    if not isinstance(ready, str) or not ready.strip():
        issues.append(
            _issue(
                "ready_missing",
                "matrix must name a 'ready' expression the checker "
                "waits for on every shot",
            )
        )
    wait_ms = matrix.get("wait_ms")
    if not _is_num(wait_ms) or float(wait_ms) <= 0:
        issues.append(
            _issue(
                "wait_missing",
                "matrix must give a positive 'wait_ms' settle value "
                "supplied by the caller",
                wait_ms=wait_ms,
            )
        )
    unexamined = plan.get("unexamined") or plan.get("not_checked")
    if not isinstance(unexamined, list) or not unexamined or not all(
        isinstance(item, str) and item.strip() for item in unexamined
    ):
        issues.append(
            _issue(
                "unexamined_missing",
                "the plan must state what was not checked in a "
                "non-empty 'unexamined' (or 'not_checked') list; "
                "silence about unexamined items is not acceptable",
            )
        )
    failure = plan.get("failure")
    if not _is_obj(failure):
        issues.append(
            _issue(
                "failure_block_missing",
                "the plan must declare a 'failure' block with "
                "exit_code_on_failure=1 and the five failure conditions",
            )
        )
        failure = {}
    if failure.get("exit_code_on_failure") != 1:
        issues.append(
            _issue(
                "exit_code_not_1",
                "any shot with a page error, 4xx/5xx, blank canvas or "
                "horizontal overflow must end the run with exit code 1",
                exit_code_on_failure=failure.get("exit_code_on_failure"),
            )
        )
    conditions = failure.get("conditions")
    if not isinstance(conditions, list):
        issues.append(
            _issue(
                "failure_conditions_missing",
                "failure must list 'conditions' covering page_error, "
                "http_4xx, http_5xx, blank_canvas and "
                "horizontal_overflow",
            )
        )
        conditions = []
    for name in REQUIRED_FAILURE_CONDITIONS:
        if name not in conditions:
            issues.append(
                _issue(
                    "failure_condition_missing",
                    f"failure conditions must include {name!r}",
                    condition=name,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "browsers": list(browsers),
        "widths": list(widths),
        "issues": issues,
    }


def check_browser_check_report(report: Any) -> dict[str, Any]:
    """Judge a check report schema and its exit-code honesty.

    Every shot must carry browser, width and a failure record; a
    report that records a failing shot but claims exit code 0
    fails. Shots with no failure record are not assumed clean:
    they fail with a named issue.
    """
    if not _is_obj(report):
        raise CapabilityError(
            "qa.browser_check_matrix: report must be a JSON object"
        )
    shots = report.get("shots")
    if not isinstance(shots, list) or not shots:
        raise CapabilityError(
            "qa.browser_check_matrix: report requires a non-empty 'shots' list"
        )
    issues: list[dict[str, Any]] = []
    saw_failure = False
    for index, shot in enumerate(shots):
        label = f"shot {index}"
        if not _is_obj(shot):
            issues.append(
                _issue("shot_not_object", f"{label} must be an object")
            )
            continue
        if shot.get("browser") not in REQUIRED_BROWSERS:
            issues.append(
                _issue(
                    "shot_browser_invalid",
                    f"{label} must name browser chromium or webkit",
                    browser=shot.get("browser"),
                )
            )
        if shot.get("width") not in REQUIRED_WIDTHS:
            issues.append(
                _issue(
                    "shot_width_invalid",
                    f"{label} must name width 1440, 768 or 390",
                    width=shot.get("width"),
                )
            )
        failures = shot.get("failures")
        if not isinstance(failures, list):
            issues.append(
                _issue(
                    "shot_failures_missing",
                    f"{label} must carry a 'failures' list (empty when "
                    "the shot is clean); a missing record is not a pass",
                )
            )
            continue
        for failure in failures:
            if failure in REQUIRED_FAILURE_CONDITIONS:
                saw_failure = True
            elif isinstance(failure, str):
                issues.append(
                    _issue(
                        "shot_failure_unknown",
                        f"{label} names unknown failure {failure!r}; "
                        "known failures are page_error, http_4xx, "
                        "http_5xx, blank_canvas, horizontal_overflow",
                        failure=failure,
                    )
                )
    exit_code = report.get("exit_code")
    if saw_failure and exit_code != 1:
        issues.append(
            _issue(
                "exit_code_dishonest",
                "the report records a failing shot but exit_code is "
                "not 1; a failing shot must end the run with exit code 1",
                exit_code=exit_code,
            )
        )
    if not saw_failure and exit_code not in (0, 1):
        issues.append(
            _issue(
                "exit_code_invalid",
                "exit_code must be 0 (clean) or 1 (failing shot)",
                exit_code=exit_code,
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "shots_checked": len(shots),
        "saw_failure": saw_failure,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = params.get("mode", "plan")
    if mode == "report":
        report = check_browser_check_report(params.get("report"))
    else:
        report = check_browser_check_plan(params.get("plan"))
    report_path = out_dir / "browser_check_matrix.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass"},
    )


def register_browser_check_matrix_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.browser_check_matrix",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "report": {"type": "object"},
                    "mode": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Browser check matrix gate (open-3d-skills site-check "
                "discipline, clean-room): a check plan must cover "
                "Chromium plus WebKit at 1440/768/390, follow deep "
                "links, wait for a caller-supplied ready expression, "
                "state what was not checked, and end with exit code 1 "
                "on any page error, 4xx/5xx, blank canvas or horizontal "
                "overflow. Judges plans and report schemas only; no "
                "browser run is performed here. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.browser_check_matrix"]


register_browser_check_matrix_capabilities_once()
