"""Knowledge QC execution contract (``qa.knowledge_qc_contract``).

Clean-room rewrite of a *contract* only: a knowledge film's quality
check names five checks — contact sheet, OCR read-back against the
source ledger, loudness, freeze detection, and background-music
correlation — and records, for each, that execution happens
elsewhere. This module performs no check itself: every check record
must declare ``executed_here: false``. A record that claims
execution here is refused, because this contract never measures
anything. No text, code, or asset from any outside repository is
copied here. See VIBE_KNOWLEDGE_ATTRIBUTION.md.

Platform lock, recorded in every report: the OCR read-back check
runs on a platform-locked OCR engine (macOS Vision) and is
unavailable on Linux. The contract records that lock; it does not
work around it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

CHECK_KINDS = (
    "contact_sheet",
    "ocr_readback",
    "loudness",
    "freeze_detection",
    "bgm_correlation",
)

OCR_PLATFORM = "macos_vision"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_qc_contract(report: Any) -> dict[str, Any]:
    """Validate one QC execution contract. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. ``executed_here`` must be
    false on every check: this contract judges the shape of the
    plan, never the footage.
    """
    issues: list[dict[str, Any]] = []
    checks_out: list[dict[str, Any]] = []
    if not isinstance(report, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("report_not_object", "QC contract report must be a JSON object")
            ],
            "checks": [],
            "ocr_platform": OCR_PLATFORM,
            "ocr_linux_available": False,
        }
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        issues.append(
            _issue("checks_missing", "contract must declare a non-empty checks list")
        )
        checks = checks if isinstance(checks, list) else []
    seen_kinds: set[str] = set()
    for index, check in enumerate(checks):
        label = f"checks[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(check, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each check must be an object")
            )
            checks_out.append(entry)
            continue
        kind = check.get("kind")
        if kind not in CHECK_KINDS:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:kind_unknown",
                    f"check kind must be one of {list(CHECK_KINDS)}",
                )
            )
        else:
            seen_kinds.add(kind)
        if check.get("executed_here") is not False:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:executed_here_claimed",
                    "this contract never executes a check; executed_here "
                    "must be false and execution must be recorded elsewhere",
                )
            )
        if kind == "ocr_readback":
            if check.get("ocr_platform") != OCR_PLATFORM:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:ocr_platform_undeclared",
                        f"the OCR read-back check is platform locked to "
                        f"{OCR_PLATFORM}; the plan must declare it",
                    )
                )
            if check.get("ocr_linux_available") is not False:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:ocr_linux_claimed",
                        "the OCR read-back check is unavailable on Linux; "
                        "the plan must record ocr_linux_available=false",
                    )
                )
        if entry["issues"]:
            entry["ok"] = False
            issues.extend(entry["issues"])
        checks_out.append(entry)
    missing = [kind for kind in CHECK_KINDS if kind not in seen_kinds]
    if missing:
        issues.append(
            _issue(
                "checks_incomplete",
                f"contract is missing check kinds: {missing}",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "checks": checks_out,
        "ocr_platform": OCR_PLATFORM,
        "ocr_linux_available": False,
        "missing_kinds": missing,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_qc_contract(params.get("report"))
    report_path = out_dir / "knowledge_qc_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_knowledge_qc_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.knowledge_qc_contract",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "report": {"type": "object"},
                },
                "required": ["report"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Knowledge QC execution contract: five named checks "
                "with executed_here always false; the OCR read-back "
                "check is recorded as platform locked to macOS Vision "
                "and unavailable on Linux."
            ),
        )
    )
    return ["qa.knowledge_qc_contract"]


__all__ = [
    "check_qc_contract",
    "register_knowledge_qc_contract_capabilities_once",
]
