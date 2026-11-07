"""Physical-language gate (``qa.physical_language_gate``).

A portrait plan must carry executable photographic physical
language in every one of eight dimensions -- anchoring, fabric,
expression, lens, light, environment, restraint, negatives --
instead of a stack of vague adjectives.  A dimension passes when
it names a vocabulary entry (resolved against the portrait or
eight-dimension indexes) or when its free text contains a
concrete term from that dimension's lexicon.  Text that contains
only vague adjectives (beautiful, pretty, and their Chinese
equivalents) fails the dimension that carries it.

The lexicons are generic photographic terms (focal lengths,
apertures, lighting and fabric names).  They are deliberately
narrow: an unrelated concrete noun does not satisfy a dimension.

Shape: ``{"dimensions": {"anchoring": "...", "fabric": "FA-01"
or ["..."], "expression": ..., "lens": ..., "light": ...,
"environment": "...", "restraint": "..." or true,
"negatives": [...]}}``.  Entry-id values may be a single id or a
list; free-text values are single strings.
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

DIMENSIONS: tuple[str, ...] = (
    "anchoring",
    "fabric",
    "expression",
    "lens",
    "light",
    "environment",
    "restraint",
    "negatives",
)

# Concrete-term lexicons, one per free-text dimension.  Generic
# photographic vocabulary only.
LEXICONS: dict[str, frozenset[str]] = {
    "anchoring": frozenset(
        {
            "old-money",
            "old money",
            "editorial",
            "时装",
            "复古",
            "学院",
            "文艺",
            "职场",
            "影调",
            "杂志",
            "胶片",
            "年代",
        }
    ),
    "fabric": frozenset(
        {
            "silk",
            "丝绸",
            "生丝",
            "merino",
            "美利奴",
            "linen",
            "亚麻",
            "velvet",
            "天鹅绒",
            "satin",
            "缎",
            "chiffon",
            "雪纺",
            "wool",
            "羊毛",
            "cotton",
            "棉",
            "knit",
            "针织",
            "drape",
            "垂坠",
            "面料",
        }
    ),
    "expression": frozenset(
        {
            "candid",
            "抓拍",
            "glance",
            "一瞥",
            "mid-reaction",
            "反应",
            "unaware",
            "未察觉",
            "smile",
            "笑",
            "laugh",
            "出神",
            "说话",
            "回头",
        }
    ),
    "lens": frozenset(
        {
            "85mm",
            "50mm",
            "35mm",
            "f/1.8",
            "f/2",
            "f/2.8",
            "aperture",
            "光圈",
            "focal",
            "焦段",
            "depth of field",
            "景深",
            "grain",
            "颗粒",
            "compression",
            "压缩",
            "bokeh",
            "虚化",
        }
    ),
    "light": frozenset(
        {
            "rim",
            "轮廓光",
            "side light",
            "侧光",
            "directional",
            "方向光",
            "diffuse",
            "柔光",
            "catchlight",
            "眼神光",
            "pores",
            "毛孔",
            "highlight",
            "高光",
            "falloff",
            "过渡",
            "backlight",
            "逆光",
        }
    ),
    "environment": frozenset(
        {
            "bokeh",
            "虚化",
            "depth of field",
            "景深",
            "defocused",
            "失焦",
            "blurred background",
            "模糊背景",
            "shallow depth",
            "浅景深",
        }
    ),
}

RESTRAINT_TERMS: frozenset[str] = frozenset(
    {
        "克制",
        "自然",
        "适度",
        "内敛",
        "understated",
        "effortless",
        "restrained",
        "muted",
    }
)

VAGUE_ADJECTIVES: frozenset[str] = frozenset(
    {
        "美丽",
        "漂亮",
        "好看",
        "精致",
        "完美",
        "迷人",
        "beautiful",
        "gorgeous",
        "stunning",
        "pretty",
        "perfect",
        "lovely",
    }
)


def _resolve_entry(raw: Any) -> bool:
    """True when the value names a vocabulary entry in either index."""
    text = str(raw).strip()
    if not text:
        return False
    try:
        from hevi.image.portrait_vocab import eight_dim as ed

        ed.get_entry(text)
        return True
    except Exception:
        pass
    try:
        from hevi.image.portrait_vocab import vocab as pv

        pv.get_entry(text)
        return True
    except Exception:
        return False


def _has_concrete_term(dim: str, text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in LEXICONS[dim])


def _dimension_ok(dim: str, value: Any) -> tuple[bool, str]:
    """Return (passes, reason) for one dimension value."""
    if dim == "negatives":
        if isinstance(value, list) and any(str(v).strip() for v in value):
            return True, "negatives_declared"
        return False, "negatives_empty"
    if dim == "restraint":
        if value is True:
            return True, "restraint_declared"
        if isinstance(value, str) and value.strip():
            if any(t in value for t in RESTRAINT_TERMS):
                return True, "restraint_declared"
            return False, "restraint_undeclared"
        return False, "restraint_missing"
    if isinstance(value, list):
        values = [v for v in value if str(v).strip()]
        if not values:
            return False, "dimension_empty"
        if all(_resolve_entry(v) for v in values):
            return True, "entry_resolved"
        joined = " ".join(str(v) for v in values)
        if dim in LEXICONS and _has_concrete_term(dim, joined):
            return True, "concrete_term"
        return False, "no_physical_language"
    if isinstance(value, str):
        if _resolve_entry(value):
            return True, "entry_resolved"
        if dim in LEXICONS:
            if _has_concrete_term(dim, value):
                return True, "concrete_term"
            if any(v in value for v in VAGUE_ADJECTIVES):
                return False, "vague_adjectives_only"
            return False, "no_physical_language"
        if value.strip():
            return True, "text_present"
        return False, "dimension_empty"
    return False, "dimension_bad_type"


def check_physical_language(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether all eight dimensions carry physical language."""
    if not isinstance(plan, dict):
        raise CapabilityError("physical-language plan must be an object")
    dims = plan.get("dimensions")
    if not isinstance(dims, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": ["dimensions_not_object: plan.dimensions must be an object"],
            "evidence": {},
        }
    issues: list[str] = []
    evidence: dict[str, str] = {}
    for dim in DIMENSIONS:
        if dim not in dims:
            issues.append(f"dim_missing: {dim}")
            continue
        ok, reason = _dimension_ok(dim, dims[dim])
        evidence[dim] = reason
        if not ok:
            issues.append(f"dim_no_physical_language: {dim} ({reason})")
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues, "evidence": evidence}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    report = check_physical_language(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "physical_language.json"
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
        },
    )


_Registered = False


def register_physical_language_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.physical_language_gate",
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
                "Physical-language gate: every one of the eight "
                "portrait dimensions must name a vocabulary entry or "
                "a concrete photographic term; vague-adjective stacks fail."
            ),
        )
    )
    return ["qa.physical_language_gate"]


register_physical_language_gate_capabilities_once()
