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
from hevi.capabilities.pure_helpers import (
    summarise_verdicts,
)
from hevi.capabilities.pure_helpers import (
    check_item_verdict,
)
from hevi.capabilities.pure_helpers import (
    _LEGACY_MAP,
    normalise_verdict,
)

_Registered = False

VERDICTS = ("pass", "fail", "not_checked")





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
