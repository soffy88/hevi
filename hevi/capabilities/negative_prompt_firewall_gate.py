"""Negative-prompt firewall gate (``qa.negative_prompt_firewall``).

A portrait plan must carry a closed firewall vocabulary: at least
one negative term from each of three classes -- deformation,
CGI-looking rendering, and over-smoothing.  The classes and terms
are restated here in generic negative-prompt vocabulary (short
standard phrases such as extra limbs or waxy skin); no article text
is copied, and no effectiveness is claimed -- this gate judges
that the plan *declares* the firewall, not that a model obeys it.

Shape: ``{"negatives": ["plastic skin", ...]}``.  Each item is
normalised (lowercased, leading ``no``/``no-``/``无``/``不要``
stripped) and matched against the class term sets, either exactly
or as a substring in either direction.  A missing class fails with
its class named.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

# Closed firewall classes.  Generic short phrases only; the sets are
# deliberately small -- callers may add synonyms, but every class
# must be covered by at least one listed term.
FIREWALL_CLASSES: dict[str, frozenset[str]] = {
    "deformation": frozenset(
        {
            "extra limbs",
            "extra fingers",
            "extra arms",
            "missing fingers",
            "deformed hands",
            "distorted face",
            "warped features",
            "多余肢体",
            "多指",
            "手指变形",
            "面部扭曲",
            "畸形",
        }
    ),
    "cgi_look": frozenset(
        {
            "3d render look",
            "cgi look",
            "doll face",
            "plastic skin",
            "video game character",
            "cartoonish",
            "3d 渲染感",
            "玩偶脸",
            "塑料感皮肤",
            "游戏角色感",
        }
    ),
    "over_smoothing": frozenset(
        {
            "over-smoothed texture",
            "over smoothed skin",
            "airbrushed skin",
            "waxy skin",
            "porcelain skin",
            "过度磨皮",
            "皮肤过度平滑",
            "蜡质皮肤",
        }
    ),
}

_LEADING_NEGATION_RE = re.compile(r"^(no[\s\-]*|无|不要|拒绝)\s*", re.IGNORECASE)


def _normalise(item: Any) -> str:
    text = str(item).strip().lower()
    text = _LEADING_NEGATION_RE.sub("", text).strip(" ,.")
    return re.sub(r"\s+", " ", text)


def _covers(term: str, item: str) -> bool:
    return term == item or term in item or item in term


def check_negative_prompt_firewall(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether a plan carries all three firewall classes."""
    if not isinstance(plan, dict):
        raise CapabilityError("firewall plan must be an object")
    negatives = plan.get("negatives")
    if not isinstance(negatives, list):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": ["negatives_not_list: plan.negatives must be a list"],
            "covered": [],
        }
    items = [_normalise(n) for n in negatives if str(n).strip()]
    covered: list[str] = []
    issues: list[str] = []
    for cls, terms in FIREWALL_CLASSES.items():
        if any(_covers(t, item) for item in items for t in terms):
            covered.append(cls)
        else:
            issues.append(
                f"firewall_class_missing: {cls} has no negative term "
                f"(want one of: {', '.join(sorted(terms)[:4])}, ...)"
            )
    if not items:
        issues.append("negatives_empty: plan declares no negative terms")
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues, "covered": covered}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    report = check_negative_prompt_firewall(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "negative_prompt_firewall.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["ok"],
            "covered": report["covered"],
        },
    )


_Registered = False


def register_negative_prompt_firewall_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.negative_prompt_firewall",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Negative-prompt firewall gate: a portrait plan must "
                "declare at least one negative term from each of the "
                "deformation, CGI-look, and over-smoothing classes."
            ),
        )
    )
    return ["qa.negative_prompt_firewall"]


register_negative_prompt_firewall_capabilities_once()
