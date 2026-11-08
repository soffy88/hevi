"""Shotcraft card fidelity gate (``qa.shotcraft_card_fidelity_gate``).

Clean-room discipline gate only. A plan that claims to use tuned
upstream shot cards must name cards from the closed 124-card
vocabulary carried by ``shotcraft_card_index.json`` (identity index
only: names, categories, style keys, provenance refs). A name from
the hevi-side synthesized 152-name catalogue
(``hevi.motion.recipe_card.build_shotcraft_library``) is NOT a tuned
card: the synthesized catalogue builds purpose text from templates
and placeholder parameters, and must never be presented as tuned
upstream cards. The gate therefore requires every card to declare
``source: "tuned"``, to carry tuned parameters, and to name a demo
reference. No card text, parameter value, pitfall text, or demo code
from any outside repository is copied here. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.

The 124-card vocabulary is a closed list. Unknown names fail; a
missing source declaration fails; a ``"synthesized"`` source fails.
This gate judges the plan only and renders nothing.
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

_INDEX_PATH = Path(__file__).with_name("shotcraft_card_index.json")
_INDEX_CACHE: dict[str, Any] | None = None


def _load_index() -> dict[str, Any]:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        _INDEX_CACHE = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    return _INDEX_CACHE


def tuned_card_names() -> frozenset[str]:
    """Return the closed 124-card tuned vocabulary."""
    return frozenset(c["name"] for c in _load_index()["cards"])


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_shotcraft_card_fidelity(plan: Any) -> dict[str, Any]:
    """Validate a shot-card plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Every card must name a
    card from the closed tuned vocabulary, declare ``source`` as
    ``"tuned"``, carry tuned parameters, and name a demo reference.
    """
    issues: list[dict[str, Any]] = []
    cards_out: list[dict[str, Any]] = []
    vocabulary = tuned_card_names()
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "card plan must be a JSON object")
            ],
            "cards": [],
            "vocabulary_size": len(vocabulary),
        }
    cards = plan.get("cards")
    if not isinstance(cards, list) or not cards:
        issues.append(
            _issue("cards_missing", "plan must declare a non-empty cards list")
        )
        cards = cards if isinstance(cards, list) else []
    for index, card in enumerate(cards):
        label = f"cards[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(card, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each card must be an object")
            )
            cards_out.append(entry)
            continue
        name = card.get("name")
        entry["name"] = name
        if not isinstance(name, str) or not name:
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:name_missing", "each card must name a card")
            )
        elif name not in vocabulary:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:unknown_card_name",
                    f"{name!r} is not in the closed 124-card tuned vocabulary",
                )
            )
        source = card.get("source")
        if source is None:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:source_undeclared",
                    "each card must declare source 'tuned'",
                )
            )
        elif source == "synthesized":
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:synthesized_catalogue_not_tuned",
                    "a synthesized catalogue name must never be presented "
                    "as a tuned upstream card",
                )
            )
        elif source != "tuned":
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:source_unknown",
                    "source must be 'tuned' (or the card fails)",
                )
            )
        if card.get("tuned_params_present") is not True:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:tuned_params_missing",
                    "tuned parameters must be declared present; "
                    "placeholder parameters fail",
                )
            )
        demo_ref = card.get("demo_ref")
        if not isinstance(demo_ref, str) or not demo_ref.startswith("demos/"):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:demo_ref_missing",
                    "each card must name a demo reference under demos/",
                )
            )
        if entry["issues"]:
            entry["ok"] = False
        cards_out.append(entry)
        issues.extend(entry["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "cards": cards_out,
        "vocabulary_size": len(vocabulary),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_shotcraft_card_fidelity(params.get("plan"))
    report_path = out_dir / "shotcraft_card_fidelity.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_shotcraft_card_fidelity_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.shotcraft_card_fidelity_gate",
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
                "Shotcraft card fidelity gate: card names must hit the "
                "closed 124-card tuned vocabulary, declare a tuned "
                "source, carry tuned parameters, and name a demo "
                "reference; synthesized catalogue names never pass "
                "as tuned cards."
            ),
        )
    )
    return ["qa.shotcraft_card_fidelity_gate"]


__all__ = [
    "check_shotcraft_card_fidelity",
    "tuned_card_names",
    "register_shotcraft_card_fidelity_gate_capabilities_once",
]
