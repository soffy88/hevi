"""Code-rendered text gate (``qa.code_rendered_text_gate``).

Discipline gate only. Text that must be exact -- prices, brand
names, rankings, and captions -- is rendered by code from the
declared source text, so what is written is what appears.
Letting a generative image or video model draw such text fails:
models misspell. When code rendering is claimed, the rendered
text must equal the source text character for character. This
gate judges the plan only and renders nothing. See
HYPIT_ATTRIBUTION.md. Method restated in our own words.
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

_CODE_ONLY_KINDS = frozenset({"price", "brand", "ranking", "caption"})


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_code_rendered_text(plan: Any) -> dict[str, Any]:
    """Check that exact text is code-rendered from source text.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Model-drawn prices, brand names, rankings,
    or captions, and code rendering whose text differs from
    the source text, all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    items = plan.get("text_items")
    if not isinstance(items, list) or not items:
        issues.append(_issue("text_items_missing", "plan must declare a non-empty text_items list"))
        items = items if isinstance(items, list) else []
    for index, item in enumerate(items):
        where = f"text_items[{index}]"
        if not isinstance(item, dict):
            issues.append(_issue(f"{where}:not_object", "each text item must be an object"))
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content:
            issues.append(_issue(f"{where}:content_missing", "each text item needs content text"))
            content = content if isinstance(content, str) else ""
        kind = item.get("kind")
        if kind not in _CODE_ONLY_KINDS:
            issues.append(
                _issue(
                    f"{where}:kind_unknown",
                    "text item kind must be one of price, brand, ranking, caption",
                )
            )
        rendered_by = item.get("rendered_by")
        if rendered_by != "code":
            issues.append(
                _issue(
                    f"{where}:model_drawn_text",
                    "exact text must be rendered by code, not drawn by a generative model",
                )
            )
        else:
            source_text = item.get("source_text")
            if source_text != content:
                issues.append(
                    _issue(
                        f"{where}:text_mismatch",
                        "code-rendered text must equal the source text",
                    )
                )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_code_rendered_text(params.get("plan"))
    report_path = out_dir / "code_rendered_text.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_code_rendered_text_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.code_rendered_text_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Code-rendered text gate (discipline only): prices, "
                "brand names, rankings, and captions are rendered "
                "by code from source text, never drawn by a model."
            ),
        )
    )
    return ["qa.code_rendered_text_gate"]


__all__ = [
    "check_code_rendered_text",
    "register_code_rendered_text_gate_capabilities_once",
]
