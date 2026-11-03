"""Markdown pagination contract gate (``qa.markdown_pagination_gate``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 3 (Knowledge Explainer): the manuscript is the
storyboard. Each section of the paginated manuscript names a layout,
carries its parameters, and declares its duration in seconds, and a
custom section's name is the name of the component that renders it --
convention over configuration. In hevi's caliber:

1. Every page declares a layout name, its parameters object, and a
   positive duration in seconds. A page that crosses into the next
   without a boundary -- a missing page entry -- fails.
2. A custom page must name its component, and the component name must
   match the page's layout name exactly. A mismatch fails.
3. The gate judges structure only. It never renders, never imports a
   renderer, and never assumes Remotion is present.

This module judges manuscript plans only.
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

_Registered = False

_CUSTOM_COMPONENT_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_markdown_pagination(document: Any) -> dict[str, Any]:
    """Judge one paginated manuscript. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    pages_out: list[dict[str, Any]] = []
    total_s = 0.0
    if not isinstance(document, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("document_not_object", "document must be a JSON object")],
            "pages": [],
            "total_duration_s": 0.0,
        }
    pages = document.get("pages")
    if not isinstance(pages, list) or not pages:
        issues.append(
            _issue("pages_missing", "document must declare a non-empty pages list")
        )
        pages = pages if isinstance(pages, list) else []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            issues.append(
                _issue("page_not_object", f"pages[{index}] must be an object")
            )
            continue
        layout = page.get("layout")
        if not _is_nonempty_str(layout):
            issues.append(
                _issue("page_layout_missing", f"pages[{index}] must name a layout")
            )
        if not isinstance(page.get("params"), dict):
            issues.append(
                _issue(
                    "page_params_missing",
                    f"pages[{index}] must carry a params object",
                )
            )
        duration = page.get("duration_s")
        if not _is_number(duration) or duration <= 0:
            issues.append(
                _issue(
                    "page_duration_missing",
                    f"pages[{index}] must declare a positive duration_s",
                )
            )
        else:
            total_s += float(duration)
        if page.get("custom") is True:
            component = page.get("component")
            if not _is_nonempty_str(component):
                issues.append(
                    _issue(
                        "custom_component_missing",
                        f"pages[{index}] is custom and must name its component",
                    )
                )
            elif not _CUSTOM_COMPONENT_RE.match(component):
                issues.append(
                    _issue(
                        "custom_component_name_invalid",
                        f"component {component!r} must be a CamelCase name",
                    )
                )
            elif _is_nonempty_str(layout) and component != layout:
                issues.append(
                    _issue(
                        "custom_component_mismatch",
                        f"custom page layout {layout!r} must equal its "
                        f"component name {component!r}",
                    )
                )
        pages_out.append({"layout": layout, "duration_s": duration})
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "pages": pages_out,
        "total_duration_s": total_s,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_markdown_pagination(params.get("document"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "markdown_pagination_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_markdown_pagination_gate_capabilities_once() -> list[str]:
    """Register ``qa.markdown_pagination_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.markdown_pagination_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "document": {"type": "object"},
                },
                "required": ["document"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Markdown pagination contract gate: every page names a "
                "layout, carries params, and declares a duration; a custom "
                "page's component name must match its layout name. "
                "Structure only -- no renderer is assumed or invoked."
            ),
            line="qa",
        )
    )
    return ["qa.markdown_pagination_gate"]


register_markdown_pagination_gate_capabilities_once()
