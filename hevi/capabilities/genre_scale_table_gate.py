"""Genre scale-rule table gate (``qa.genre_scale_table_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / A5: a plan's scale rules must be declared as a table,
not implied. The table states the genre's boundaries in the
caller's own words -- including the minor boundary, the
intimacy boundary, and the crime/ritual boundaries where the
genre has them -- and the plan's declared content flags must
not contradict it. A missing table fails; a crossed boundary
fails. Genre-specific requirements are stated in this module's
own words from the method report; no template text is copied.

Scope, stated plainly: this gate judges plan text only. It is
not an execution block, not a classifier, and not a substitute
for hevi's existing content gates or Soffy's own rulings. A
caller that lies in the table cannot be caught by this gate --
that limit is recorded in the evidence.

This module judges plans only. It reads no media bytes and
calls no generator.
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

# Genre keys: template slug -> display name. Requirements are the
# genre-specific declarations the method report records, restated
# here as field names the caller must affirm in the scale table.
GENRES: dict[str, dict[str, Any]] = {
    "chongsheng": {"name": "重生", "required_flags": []},
    "chuanyue": {"name": "穿越", "required_flags": []},
    "dushi": {"name": "都市", "required_flags": []},
    "gongdou": {"name": "宫斗", "required_flags": []},
    "jiating": {"name": "家庭", "required_flags": []},
    "minsu": {
        "name": "民俗",
        "required_flags": ["no_ritual_tutorials", "reveals_human_cause"],
    },
    "moshi": {"name": "末世", "required_flags": []},
    "niandai": {"name": "年代", "required_flags": []},
    "quanmou": {"name": "权谋", "required_flags": []},
    "shangzhan": {"name": "商战", "required_flags": []},
    "tianchong": {
        "name": "甜宠",
        "required_flags": ["protagonists_adult", "no_romanticized_coercion"],
    },
    "wuxia": {"name": "武侠", "required_flags": []},
    "xiaoyuan": {
        "name": "校园",
        "required_flags": [
            "min_character_age_18_or_above",
            "university_setting",
            "no_middle_school_elements",
        ],
    },
    "xihuan": {"name": "西幻", "required_flags": []},
    "xingji": {"name": "星际", "required_flags": []},
    "xitong": {"name": "系统", "required_flags": []},
    "xuanhuan": {
        "name": "玄幻",
        "required_flags": ["no_underage_age_numbers"],
    },
    "xuanyi": {
        "name": "悬疑",
        "required_flags": ["no_crimes_against_minors", "no_imitable_methods"],
    },
    "yule": {"name": "娱乐", "required_flags": []},
    "zhaidou": {"name": "宅斗", "required_flags": []},
    "zhongtian": {"name": "种田", "required_flags": []},
}

_NAME_TO_SLUG = {spec["name"]: slug for slug, spec in GENRES.items()}

# Declared content flags that contradict every scale table.
_PROHIBITED_FLAGS = {
    "minor_crime",
    "imitable_method",
    "ritual_tutorial",
    "underage_romance",
}


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _resolve_genre(value: Any) -> str | None:
    if not _is_nonempty_str(value):
        return None
    key = value.strip()
    if key in GENRES:
        return key
    return _NAME_TO_SLUG.get(key)


def check_genre_scale(plan: Any) -> dict[str, Any]:
    """Judge one genre scale plan. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only. This gate judges the
    declared table and flags only; it is not an execution block.
    """
    issues: list[dict[str, Any]] = []
    genre_slug = None
    table: dict[str, Any] = {}

    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "genre": None,
            "scope": "plan_text_only_not_execution_block",
            "issues": [
                _issue(
                    "plan_not_object",
                    "qa.genre_scale_table_gate: scale plan must be an "
                    "object",
                )
            ],
        }

    genre_slug = _resolve_genre(plan.get("genre"))
    if genre_slug is None:
        issues.append(
            _issue(
                "genre_unknown",
                "qa.genre_scale_table_gate: 'genre' must name one of the "
                "21 registered genres (slug or display name)",
            )
        )

    raw_table = plan.get("scale_table")
    if not isinstance(raw_table, dict):
        issues.append(
            _issue(
                "scale_table_missing",
                "qa.genre_scale_table_gate: the plan must declare a "
                "'scale_table'; an undeclared scale is not a kept scale",
            )
        )
    else:
        table = raw_table
        min_age = table.get("min_character_age")
        if not isinstance(min_age, int) or isinstance(min_age, bool) or min_age < 0:
            issues.append(
                _issue(
                    "min_character_age_missing",
                    "qa.genre_scale_table_gate: 'scale_table' must declare "
                    "'min_character_age' as a non-negative integer",
                )
            )
        boundaries = table.get("boundaries")
        if (
            not isinstance(boundaries, list)
            or not boundaries
            or not all(_is_nonempty_str(b) for b in boundaries)
        ):
            issues.append(
                _issue(
                    "boundaries_missing",
                    "qa.genre_scale_table_gate: 'scale_table' must declare "
                    "a non-empty 'boundaries' list in the caller's own "
                    "words",
                )
            )
        if genre_slug is not None:
            for flag in GENRES[genre_slug]["required_flags"]:
                if table.get(flag) is not True:
                    issues.append(
                        _issue(
                            "genre_boundary_undeclared",
                            f"qa.genre_scale_table_gate: genre "
                            f"{GENRES[genre_slug]['name']} requires "
                            f"'{flag}: true' in the scale table",
                        )
                    )

    flags = plan.get("content_flags")
    if isinstance(flags, list):
        bad = [f for f in flags if f in _PROHIBITED_FLAGS]
        if bad:
            issues.append(
                _issue(
                    "declared_prohibited_content",
                    "qa.genre_scale_table_gate: the plan declares "
                    f"prohibited content flags {sorted(bad)}",
                )
            )

    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "genre": genre_slug,
        "genre_name": GENRES[genre_slug]["name"] if genre_slug else None,
        "scope": "plan_text_only_not_execution_block",
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_genre_scale(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "genre_scale_table_gate_report.json"
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


def register_genre_scale_table_gate_capabilities_once() -> list[str]:
    """Register ``qa.genre_scale_table_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.genre_scale_table_gate",
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
            description=(
                "Genre scale-rule table gate: the scale rules must be "
                "declared as a table with a minimum character age and a "
                "boundaries list, plus the genre's own boundary flags; a "
                "missing table or a crossed boundary fails. Judges plan "
                "text only; not an execution block."
            ),
            line="qa",
        )
    )
    return ["qa.genre_scale_table_gate"]


register_genre_scale_table_gate_capabilities_once()
