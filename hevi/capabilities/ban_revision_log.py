"""Ban revision log (``qa.ban_revision_log``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 5 ("bans concrete, revisions logged"): bans are listed one by one,
and revoking an earlier rule is done by naming it -- "overturn rule X"
-- with the change recorded. A ban list is a list of rules, each with
a stable ``rule_id`` and a ``text``. A revision log applies, in order,
three actions:

* ``add`` -- a new rule_id with new text. Reusing an existing rule_id
  with different text is a silent overwrite and fails.
* ``supersede`` -- names ``supersedes`` (an existing rule_id) and
  supplies replacement text. The superseded rule's original text is
  kept in the ``retired`` list: nothing is silently rewritten, and
  the audit trail shows exactly what was overturned and by what.
* ``retire`` -- names ``supersedes`` and removes the rule without a
  replacement; the original text is likewise kept in ``retired``.

Dropping a rule_id without a log entry, editing text in place with
no entry, or superseding a rule_id that does not exist all fail.
The final list renders to plain strings, so it stays a drop-in
carrier for ``negative_prompts`` (see ``story.prompt_compiler``,
which dedupes and renders the same shape).

This module judges text only. It calls no generator and spends
nothing.
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

_REVISION_ACTIONS = ("add", "supersede", "retire")


def _is_ban_item(item: Any) -> bool:
    if isinstance(item, str):
        return bool(item.strip())
    if isinstance(item, dict):
        return isinstance(item.get("rule_id"), str) \
            and bool(item["rule_id"].strip()) \
            and isinstance(item.get("text"), str) \
            and bool(item["text"].strip())
    return False


def _normalise_ban(item: Any) -> dict[str, str]:
    """One ban item to ``{rule_id, text}``. String items are rejected here.

    A bare string carries no rule_id, so it cannot take part in a
    revision chain; callers that only need a flat list should use
    :func:`render_ban_list` on a checked list instead.
    """
    if isinstance(item, dict):
        return {"rule_id": str(item["rule_id"]).strip(),
                "text": str(item["text"]).strip()}
    raise CapabilityError(
        "qa.ban_revision_log: ban items must be objects with rule_id "
        "and text; a bare string cannot be revised by rule_id"
    )


def check_ban_list(bans: Any) -> dict[str, Any]:
    """Validate a ban list's shape: rule_ids present, unique, texts non-empty."""
    issues: list[dict[str, Any]] = []
    rules: list[dict[str, str]] = []
    if not isinstance(bans, list):
        return {
            "ok": False,
            "rules": [],
            "issues": [{
                "code": "bans_not_list",
                "detail": "qa.ban_revision_log: ban list must be a list",
            }],
        }
    seen: set[str] = set()
    for index, item in enumerate(bans):
        if not _is_ban_item(item):
            issues.append({
                "code": "bad_ban_item",
                "detail": f"qa.ban_revision_log: ban item {index} must be "
                         "an object with a non-empty rule_id and text",
            })
            continue
        rule = _normalise_ban(item)
        if rule["rule_id"] in seen:
            issues.append({
                "code": "duplicate_rule_id",
                "detail": f"qa.ban_revision_log: rule_id "
                         f"{rule['rule_id']!r} appears twice; rule_ids "
                         "must be unique so a revision can name its target",
            })
            continue
        seen.add(rule["rule_id"])
        rules.append(rule)
    return {"ok": not issues, "rules": rules, "issues": issues}


def render_ban_list(rules: list[dict[str, str]]) -> list[str]:
    """Checked rules to plain strings (``negative_prompts`` shape)."""
    return [rule["text"] for rule in rules]


def apply_ban_revisions(
    bans: Any,
    revision_log: Any,
) -> dict[str, Any]:
    """Apply a revision log to a ban list, in order. Returns a report.

    The returned ``rules`` are the live list and ``retired`` holds
    every superseded/retired rule with its original text plus the
    rule_id that replaced or retired it. A log that silently
    overwrites, drops, or names a missing rule fails the whole
    application: partial application is never reported as success.
    """
    base = check_ban_list(bans)
    if not base["ok"]:
        return {**base, "retired": []}
    live: dict[str, str] = {r["rule_id"]: r["text"] for r in base["rules"]}
    order: list[str] = [r["rule_id"] for r in base["rules"]]
    retired: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = list(base["issues"])

    if revision_log is None:
        revision_log = []
    if not isinstance(revision_log, list):
        issues.append({
            "code": "revision_log_not_list",
            "detail": "qa.ban_revision_log: revision_log must be a list",
        })
        return {"ok": False,
                "rules": [dict(base["rules"][i])
                          for i in range(len(base["rules"]))],
                "retired": retired, "issues": issues}
    for index, entry in enumerate(revision_log):
        label = f"revision {index}"
        if not isinstance(entry, dict):
            issues.append({
                "code": "bad_revision_entry",
                "detail": f"qa.ban_revision_log: {label} must be an object",
            })
            continue
        action = entry.get("action")
        if action not in _REVISION_ACTIONS:
            issues.append({
                "code": "bad_revision_action",
                "detail": f"qa.ban_revision_log: {label} action must be one "
                         f"of {', '.join(_REVISION_ACTIONS)}",
            })
            continue
        rule_id = entry.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            issues.append({
                "code": "bad_revision_rule_id",
                "detail": f"qa.ban_revision_log: {label} needs a non-empty "
                         "rule_id",
            })
            continue
        rule_id = rule_id.strip()
        if action == "add":
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                issues.append({
                    "code": "bad_revision_text",
                    "detail": f"qa.ban_revision_log: {label} (add) needs "
                             "non-empty text",
                })
                continue
            if rule_id in live:
                if live[rule_id] == text.strip():
                    issues.append({
                        "code": "redundant_add",
                        "detail": f"qa.ban_revision_log: {label} re-adds "
                                 f"rule {rule_id!r} with identical text; "
                                 "use supersede to change a rule",
                    })
                else:
                    issues.append({
                        "code": "silent_overwrite",
                        "detail": f"qa.ban_revision_log: {label} reuses "
                                 f"existing rule_id {rule_id!r} with "
                                 "different text and no supersede entry; "
                                 "silent overwrites are refused -- name "
                                 "the rule being overturned",
                    })
                continue
            live[rule_id] = text.strip()
            order.append(rule_id)
            continue
        # supersede / retire: must name an existing rule.
        target = entry.get("supersedes")
        if not isinstance(target, str) or not target.strip():
            issues.append({
                "code": "supersede_without_target",
                "detail": f"qa.ban_revision_log: {label} ({action}) must "
                         "name 'supersedes': the rule_id being overturned",
            })
            continue
        target = target.strip()
        if target not in live:
            issues.append({
                "code": "supersede_missing_target",
                "detail": f"qa.ban_revision_log: {label} ({action}) names "
                         f"supersedes {target!r}, which is not a live rule",
            })
            continue
        retired.append({
            "rule_id": target,
            "text": live[target],
            "overturned_by": rule_id,
            "action": action,
        })
        del live[target]
        order.remove(target)
        if action == "supersede":
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                issues.append({
                    "code": "bad_revision_text",
                    "detail": f"qa.ban_revision_log: {label} (supersede) "
                             "needs non-empty replacement text",
                })
                continue
            if rule_id in live:
                issues.append({
                    "code": "supersede_reuses_live_id",
                    "detail": f"qa.ban_revision_log: {label} (supersede) "
                             f"reuses live rule_id {rule_id!r} as the "
                             "replacement id; use a fresh rule_id",
                })
                continue
            live[rule_id] = text.strip()
            order.append(rule_id)

    rules = [{"rule_id": rid, "text": live[rid]} for rid in order]
    return {
        "ok": not issues,
        "rules": rules,
        "retired": retired,
        "issues": issues,
        "rendered": render_ban_list(rules),
    }


def authorize_ban_revisions(
    bans: Any,
    revision_log: Any,
) -> dict[str, Any]:
    """Apply a revision log, or refuse it loudly (raises CapabilityError)."""
    report = apply_ban_revisions(bans, revision_log)
    if not report["ok"]:
        raise CapabilityError(
            "qa.ban_revision_log: ban revision refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_ban_revisions(
        params.get("bans"), params.get("revision_log"))
    report_path = out_dir / "ban_revision_log.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "rules": len(report["rules"]),
            "retired": len(report["retired"])},
    )


def register_ban_revision_log_capabilities_once() -> list[str]:
    """Register ``qa.ban_revision_log`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ban_revision_log",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "bans": {"type": "array"},
                    "revision_log": {"type": "array"},
                },
                "required": ["bans"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Ban revision log: every ban carries a rule_id; a rule "
                "is changed only by an explicit supersede entry naming "
                "the overturned rule_id, whose original text is kept in "
                "the retired list. Silent overwrites, drops without a "
                "log entry, and supersedes of missing rules fail. The "
                "live list renders to plain strings for negative_prompts."
            ),
            line="qa",
        )
    )
    return ["qa.ban_revision_log"]


register_ban_revision_log_capabilities_once()
