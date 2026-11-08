"""Per-sentence source ledger gate (``qa.source_sentence_ledger``).

Clean-room rewrite of a *method* only: every spoken sentence in a
knowledge film carries its own source record; a disputed claim shows
both sides; an illustrative picture is marked illustrative and never
presented as sourced fact. No text, code, or asset from any outside
repository is copied here. See VIBE_KNOWLEDGE_ATTRIBUTION.md.

There is no pre-existing citation module in hevi: ``facts_discipline``
checks on-screen wording only. This gate is the first per-sentence
source ledger. It judges plans; it performs no lookup and no
verification of the sources themselves.
"""

from __future__ import annotations

import re
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|万|亿|千|k|K|M)?")
_NAME_YEAR_RE = re.compile(r"(?:19|20)\d{2}年?|(?:19|20)\d{2}")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source_ok(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    return _is_nonempty_str(source.get("label")) and _is_nonempty_str(
        source.get("locator")
    )


def check_source_sentence_ledger(plan: Any) -> dict[str, Any]:
    """Judge one per-sentence source ledger. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. ``not_checked`` is never
    returned: a missing ledger is a failure, not a skip.
    """
    issues: list[dict[str, Any]] = []
    sentences_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "source ledger plan must be a JSON object")
            ],
            "sentences": [],
        }
    sentences = plan.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        issues.append(
            _issue(
                "sentences_missing",
                "plan must declare a non-empty sentences list",
            )
        )
        sentences = sentences if isinstance(sentences, list) else []
    for index, sentence in enumerate(sentences):
        label = f"sentences[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(sentence, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each sentence must be an object")
            )
            sentences_out.append(entry)
            continue
        text = sentence.get("text")
        if not _is_nonempty_str(text):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:text_missing", "each sentence must carry text")
            )
            sentences_out.append(entry)
            continue
        kind = sentence.get("kind", "fact")
        if kind not in ("fact", "illustration", "opinion"):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:kind_unknown",
                    "kind must be one of fact, illustration, opinion",
                )
            )
        sources = sentence.get("sources", [])
        good_sources = (
            [s for s in sources if _source_ok(s)]
            if isinstance(sources, list)
            else []
        )
        if kind == "fact":
            if not good_sources:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:source_missing",
                        "a factual sentence needs at least one source "
                        "with a label and a locator",
                    )
                )
            if sentence.get("disputed") is True:
                sides = sentence.get("sides")
                side_labels = set()
                for source in good_sources:
                    side = source.get("side")
                    if _is_nonempty_str(side):
                        side_labels.add(str(side).strip())
                if isinstance(sides, list):
                    for side in sides:
                        if _is_nonempty_str(side):
                            side_labels.add(str(side).strip())
                if len(side_labels) < 2:
                    entry["ok"] = False
                    entry["issues"].append(
                        _issue(
                            f"{label}:dispute_one_sided",
                            "a disputed claim must show both sides, each "
                            "with its own source side label",
                        )
                    )
            if _NUMBER_RE.search(str(text)) or _NAME_YEAR_RE.search(str(text)):
                if not good_sources:
                    entry["ok"] = False
                    entry["issues"].append(
                        _issue(
                            f"{label}:number_or_year_unsourced",
                            "a number, name-year, or date in the text needs "
                            "a source on the same sentence",
                        )
                    )
        if kind == "illustration":
            if sentence.get("illustrative_marker") is not True:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:illustrative_unmarked",
                        "an illustrative sentence must carry "
                        "illustrative_marker=true",
                    )
                )
            if good_sources and sentence.get("presented_as_fact") is True:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:illustration_as_fact",
                        "an illustrative sentence must never be presented "
                        "as sourced fact",
                    )
                )
        if kind == "opinion" and sentence.get("presented_as_fact") is True:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:opinion_as_fact",
                    "an opinion sentence must never be presented as fact",
                )
            )
        if entry["issues"]:
            entry["ok"] = False
            issues.extend(entry["issues"])
        sentences_out.append(entry)
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "sentences": sentences_out,
        "sentence_count": len(sentences_out),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    from pathlib import Path
    import json

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_source_sentence_ledger(params.get("plan"))
    report_path = out_dir / "source_sentence_ledger.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_source_sentence_ledger_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.source_sentence_ledger",
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
                "Per-sentence source ledger: factual sentences need a "
                "labelled source, disputed claims show both sides, and "
                "illustrative sentences are marked illustrative."
            ),
        )
    )
    return ["qa.source_sentence_ledger"]


__all__ = [
    "check_source_sentence_ledger",
    "register_source_sentence_ledger_capabilities_once",
]
