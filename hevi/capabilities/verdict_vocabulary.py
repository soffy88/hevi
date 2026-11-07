"""Verdict vocabulary (``qa.verdict_vocabulary``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 6 ("three-state verdicts"): every check item gets exactly one of
three conclusions -- ``pass``, ``fail``, ``not_checked`` -- and "not
checked" must be said out loud, never silently counted as a pass.
hevi already lives this discipline in two dialects: ``qa.final_qc_gate``
reports unrun checks as ``pass: None`` with detail ``"skipped: ..."``,
and ``qa.prompt_eval_harness`` reports unmeasured items as
``planned_not_measured``. This module is the single vocabulary both
dialects map into, so a caller can read any gate's output the same
way. It invents no new discipline: it only names the one that
already exists.

Mapping (legacy -> vocabulary):

* ``True`` / ``"pass"`` -> ``pass``
* ``False`` / ``"fail"`` -> ``fail``
* ``None`` / ``"skipped"`` / ``"planned_not_measured"`` /
  ``"not_checked"`` -> ``not_checked``

Anything else is not a verdict and raises :class:`CapabilityError`
instead of being guessed. ``summarise_verdicts`` applies the
all-or-nothing rule: any ``fail`` makes the whole report ``fail``;
otherwise any ``not_checked`` makes it ``not_checked``; only a
report with every item ``pass`` is ``pass``. A ``not_checked``
item is never a pass, in any dialect.
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

VERDICTS = ("pass", "fail", "not_checked")

_LEGACY_MAP: dict[Any, str] = {
    True: "pass",
    False: "fail",
    None: "not_checked",
    "pass": "pass",
    "fail": "fail",
    "not_checked": "not_checked",
    "skipped": "not_checked",
    "planned_not_measured": "not_checked",
}


def normalise_verdict(value: Any) -> str:
    """One legacy verdict value to the single vocabulary. Raises otherwise."""
    if isinstance(value, str):
        key: Any = value.strip().lower()
    else:
        key = value
    # bool is a subclass of int: check identity first via the map keys.
    if key in _LEGACY_MAP and not isinstance(key, (int, float)):
        return _LEGACY_MAP[key]
    if value is True:
        return "pass"
    if value is False:
        return "fail"
    if value is None:
        return "not_checked"
    raise CapabilityError(
        "qa.verdict_vocabulary: "
        f"{value!r} is not a verdict; use pass, fail, or not_checked "
        "(legacy: true/false/null, skipped, planned_not_measured)"
    )


def to_legacy_pass(verdict: str) -> bool | None:
    """Vocabulary verdict back to ``qa.final_qc_gate``'s ``pass`` field."""
    if verdict == "pass":
        return True
    if verdict == "fail":
        return False
    if verdict == "not_checked":
        return None
    raise CapabilityError(
        f"qa.verdict_vocabulary: {verdict!r} is not a verdict; "
        "use pass, fail, or not_checked"
    )


def check_item_verdict(item: Any) -> dict[str, Any]:
    """Normalise one check item's verdict field.

    Accepts ``verdict`` (vocabulary or legacy string) or ``pass``
    (``True``/``False``/``None``). An item carrying neither, or
    carrying both in disagreement, fails the normalisation.
    """
    if not isinstance(item, dict):
        return {"ok": False, "verdict": None, "issues": [{
            "code": "item_not_object",
            "detail": "qa.verdict_vocabulary: check item must be an object",
        }]}
    verdicts: list[str] = []
    issues: list[dict[str, Any]] = []
    if "verdict" in item:
        try:
            verdicts.append(normalise_verdict(item["verdict"]))
        except CapabilityError as exc:
            issues.append({"code": "bad_verdict", "detail": str(exc)})
    if "pass" in item:
        try:
            verdicts.append(normalise_verdict(item["pass"]))
        except CapabilityError as exc:
            issues.append({"code": "bad_verdict", "detail": str(exc)})
    if not verdicts and not issues:
        issues.append({
            "code": "verdict_missing",
            "detail": "qa.verdict_vocabulary: check item carries neither "
                     "'verdict' nor 'pass'; an unjudged item must say "
                     "not_checked, not stay silent",
        })
    if len(verdicts) > 1 and verdicts[0] != verdicts[1]:
        issues.append({
            "code": "verdict_disagreement",
            "detail": "qa.verdict_vocabulary: item 'verdict' and 'pass' "
                     f"disagree ({verdicts[0]} vs {verdicts[1]}); fix the "
                     "item instead of guessing which one wins",
        })
    verdict = verdicts[0] if verdicts else None
    return {"ok": not issues, "verdict": verdict, "issues": issues}


def summarise_verdicts(items: Any) -> dict[str, Any]:
    """Overall verdict for a list of check items (all-or-nothing).

    ``fail`` if any item fails; else ``not_checked`` if any item was
    not checked; else ``pass``. Counts are reported so a caller can
    see exactly how much was actually checked.
    """
    if not isinstance(items, list):
        raise CapabilityError(
            "qa.verdict_vocabulary: summarise_verdicts needs a list of "
            "check items"
        )
    counts = {"pass": 0, "fail": 0, "not_checked": 0}
    normalised: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        checked = check_item_verdict(item)
        if not checked["ok"]:
            issues.extend(
                {**i, "item_index": index} for i in checked["issues"])
            continue
        verdict = checked["verdict"]
        assert verdict is not None
        counts[verdict] += 1
        normalised.append({"item_index": index, "verdict": verdict})
    if issues:
        return {"ok": False, "verdict": "fail", "counts": counts,
                "items": normalised, "issues": issues}
    if counts["fail"]:
        overall = "fail"
    elif counts["not_checked"]:
        overall = "not_checked"
    else:
        overall = "pass"
    return {"ok": True, "verdict": overall, "counts": counts,
            "items": normalised, "issues": []}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = summarise_verdicts(params.get("items"))
    report_path = out_dir / "verdict_vocabulary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "counts": report["counts"]},
    )


def register_verdict_vocabulary_capabilities_once() -> list[str]:
    """Register ``qa.verdict_vocabulary`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.verdict_vocabulary",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                },
                "required": ["items"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Verdict vocabulary: the single three-state vocabulary "
                "(pass / fail / not_checked) that final_qc_gate's "
                "skipped dialect and prompt_eval_harness's "
                "planned_not_measured dialect both map into. "
                "Summarising is all-or-nothing: any fail fails the "
                "report, any not_checked keeps it not_checked, and "
                "only an all-pass report passes. Not-checked is never "
                "counted as a pass."
            ),
            line="qa",
        )
    )
    return ["qa.verdict_vocabulary"]


register_verdict_vocabulary_capabilities_once()
