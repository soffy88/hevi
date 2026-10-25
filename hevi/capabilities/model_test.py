"""Pre-batch model test -- ``story.model_test``.

"Test before batch": before a model is used for a whole batch of
shots, a small representative test set (characters, scenes, key
shots) is scored on four dimensions -- texture, lighting naturalness,
character consistency and action accuracy -- and the scorecard says
whether batch production is released.

This capability never calls any generation API and never invents a
score. Scores come only from an injected ``eval_fn(kind, item)`` --
a human rating or an automated judge supplied by the caller. With no
``eval_fn`` the scorecard is ``status: pending`` with no numbers at
all. With an ``eval_fn``, every item must return all four dimensions
as numbers in [0, 10]; a missing dimension, an out-of-range score or
a raising judge marks that item ``error`` and keeps the whole card
``pending`` -- partial scores are never averaged into a release.

Release conditions (all must hold):

1. The test set is non-empty (at least one character, scene or key
   shot is not required -- any non-empty set counts, but the
   composition is always reported so a thin set is visible).
2. Every test item has a complete score.
3. Every dimension mean is >= ``release_threshold`` (default 7.0).
4. No scored item carries uncertain evidence (see below). Grades
   are only applied when the caller supplies them; unsupplied grades
   never block a plain scorecard call.

Method-level references (own wording, no code or text copied):

* Four confirmation gates: direction, core assets, pilot shots,
  delivery. The pilot gate IS the scorecard -- a pilot that fails
  never releases a batch. The gates are always reported and only
  bind the release decision when ``require_confirmation_gates`` is
  true, so plain scorecard calls keep their previous semantics.
* Evidence grading: every item may carry an evidence grade --
  observed, uncertain, or user_specified. Uncertain evidence blocks
  release however good the numbers look; ungraded items are reported
  as "unspecified", never silently upgraded to observed.

Output (``model_test.json``) mirrors the sibling report shape:
``composition`` (character/scene/key-shot counts),
``dimension_means``, ``overall_mean``, ``items`` (per-item scores or
pending/error), ``release_conditions``, ``released``, ``status``
(``released`` / ``not_released`` / ``pending``), ``findings`` and a
deterministic ``recommendation``. The CLI path reads JSON params and
therefore cannot inject an ``eval_fn``; a CLI run is always pending
by construction, which is the honest result for that path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("texture", "质感"),
    ("lighting", "光线自然度"),
    ("consistency", "人物一致性"),
    ("action_accuracy", "动作准确度"),
)

DIMENSION_KEYS = [key for key, _ in DIMENSIONS]

DEFAULT_RELEASE_THRESHOLD = 7.0


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def _finding(
    check: str,
    severity: str,
    issue: str,
    suggestion: str,
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "shot_id": None,
        "scene_id": None,
        "issue": issue,
        "suggestion": suggestion,
    }


def _flatten_test_set(test_set: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Flatten {characters, scenes, key_shots} into scored items."""
    items: list[dict[str, Any]] = []
    counts = {"character_count": 0, "scene_count": 0, "key_shot_count": 0}
    mapping = (
        ("characters", "character", "character_count"),
        ("scenes", "scene", "scene_count"),
        ("key_shots", "key_shot", "key_shot_count"),
    )
    for field, kind, count_key in mapping:
        raw_list = test_set.get(field, []) or []
        if not isinstance(raw_list, list):
            raise CapabilityError(
                f"story.model_test: test_set.{field} must be a list"
            )
        for idx, raw in enumerate(raw_list):
            if not isinstance(raw, dict):
                raise CapabilityError(
                    f"story.model_test: test_set.{field}[{idx}] must be an object"
                )
            item_id = _nonempty(raw.get("id")) or f"{kind}_{idx + 1}"
            label = (
                _nonempty(raw.get("name"))
                or _nonempty(raw.get("title"))
                or _nonempty(raw.get("description"))
                or item_id
            )
            items.append({"kind": kind, "id": item_id, "label": label})
            counts[count_key] += 1
    return items, counts


def _validate_scores(raw: Any) -> tuple[dict[str, float] | None, str | None]:
    """Validate one eval_fn return: all four dims, numbers in [0, 10]."""
    if not isinstance(raw, dict):
        return None, "评测返回不是对象，无法取分。"
    missing = [key for key in DIMENSION_KEYS if key not in raw]
    if missing:
        return None, f"评测缺维度：{', '.join(missing)}（四项缺一不可）。"
    scores: dict[str, float] = {}
    for key in DIMENSION_KEYS:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"维度 {key} 的分数不是数字。"
        if value < 0 or value > 10:
            return None, f"维度 {key} 的分数 {value:g} 超出 0-10 范围。"
        scores[key] = float(value)
    return scores, None


EVIDENCE_GRADES = ("observed", "uncertain", "user_specified")


def _direction_confirmed(direction: Any) -> bool:
    if isinstance(direction, bool):
        return direction
    if isinstance(direction, dict):
        return bool(direction.get("confirmed", False))
    return False


def _item_evidence(
    item_id: str, evidence_grades: dict[str, Any] | None
) -> tuple[str, dict[str, str]]:
    """Grade one item's evidence (method-level reference, own wording).

    Grades: observed (directly seen), uncertain (not confirmed),
    user_specified (the caller asserted it). With no grade supplied
    the item is "unspecified" -- no grade is invented. An uncertain
    grade anywhere in the item makes the whole item uncertain: an
    uncertain fact cannot support a release.
    """
    if not isinstance(evidence_grades, dict) or item_id not in evidence_grades:
        return "unspecified", {}
    raw = evidence_grades[item_id]
    if isinstance(raw, str):
        if raw not in EVIDENCE_GRADES:
            raise CapabilityError(
                f"story.model_test: unknown evidence grade {raw!r} for "
                f"item {item_id} (allowed: {EVIDENCE_GRADES})"
            )
        return raw, {key: raw for key in DIMENSION_KEYS}
    if isinstance(raw, dict):
        per_dim: dict[str, str] = {}
        for key in DIMENSION_KEYS:
            value = raw.get(key)
            if value is None:
                per_dim[key] = "unspecified"
            elif value not in EVIDENCE_GRADES:
                raise CapabilityError(
                    f"story.model_test: unknown evidence grade {value!r} "
                    f"for item {item_id} dimension {key}"
                )
            else:
                per_dim[key] = value
        distinct = set(per_dim.values())
        if "uncertain" in distinct:
            return "uncertain", per_dim
        if len(distinct) == 1:
            return next(iter(distinct)), per_dim
        return "mixed", per_dim
    raise CapabilityError(
        f"story.model_test: evidence grade for item {item_id} must be "
        "a grade string or a per-dimension object"
    )


def _confirmation_gates(
    direction_ok: bool, counts: dict[str, int], pilot_status: str
) -> list[dict[str, Any]]:
    """Four confirmation gates (method-level reference, own wording).

    Direction (caller-confirmed, hence user_specified evidence),
    core assets (observed from the test set: at least one character
    and one scene), pilot shots (the scorecard itself -- a pilot that
    fails never releases a batch), and delivery (passed only when the
    other three pass). Gates are always reported; they only bind the
    release decision when ``require_confirmation_gates`` is true, so
    a plain scorecard call keeps its previous release semantics.
    """
    core_ok = counts["character_count"] >= 1 and counts["scene_count"] >= 1
    gates = [
        {
            "gate": "direction",
            "label": "方向",
            "status": "passed" if direction_ok else "pending",
            "evidence": "user_specified" if direction_ok else None,
        },
        {
            "gate": "core_assets",
            "label": "核心资产",
            "status": "passed" if core_ok else "failed",
            "evidence": "observed",
        },
        {
            "gate": "pilot_shots",
            "label": "试点镜",
            "status": pilot_status,
            "evidence": "observed" if pilot_status != "pending" else None,
        },
    ]
    gates.append(
        {
            "gate": "delivery",
            "label": "交付",
            "status": (
                "passed"
                if all(g["status"] == "passed" for g in gates)
                else "pending"
            ),
            "evidence": None,
        }
    )
    return gates


def build_scorecard(
    test_set: dict[str, Any] | None,
    eval_fn: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    release_threshold: float = DEFAULT_RELEASE_THRESHOLD,
    evidence_grades: dict[str, Any] | None = None,
    direction: Any = None,
    require_confirmation_gates: bool = False,
) -> dict[str, Any]:
    """Pure build step (no file I/O): test set -> model scorecard."""
    if (
        isinstance(release_threshold, bool)
        or not isinstance(release_threshold, (int, float))
        or release_threshold < 0
        or release_threshold > 10
    ):
        raise CapabilityError(
            "story.model_test: release_threshold must be a number in [0, 10]"
        )
    threshold = float(release_threshold)
    if not isinstance(test_set, dict):
        raise CapabilityError("story.model_test: 'test_set' must be an object")
    if evidence_grades is not None and not isinstance(evidence_grades, dict):
        raise CapabilityError(
            "story.model_test: 'evidence_grades' must be an object"
        )
    direction_ok = _direction_confirmed(direction)
    items, counts = _flatten_test_set(test_set)
    total = len(items)
    findings: list[dict[str, Any]] = []
    scored_items: list[dict[str, Any]] = []
    errored = 0
    if total == 0:
        findings.append(
            _finding(
                "model_test",
                "blocker",
                "测试集为空：无人物、无场景、无关键镜头，无法评测模型。",
                "至少给出一个人物、一个场景或一个关键镜头后再评测。",
            )
        )
        return {
            "composition": {**counts, "total_items": 0},
            "dimension_means": None,
            "overall_mean": None,
            "items": [],
            "release_conditions": [
                {"condition": "测试集非空", "met": False},
                {"condition": "全部测试项均已评分", "met": False},
                {
                    "condition": f"四项均值均 >= {threshold:g}",
                    "met": False,
                },
                {"condition": "证据等级无不确定项", "met": True},
            ],
            "confirmation_gates": _confirmation_gates(
                direction_ok, counts, "pending"
            ),
            "evidence_summary": {},
            "released": False,
            "status": "pending",
            "release_threshold": threshold,
            "findings": findings,
            "recommendation": "不放行批量：测试集为空，先补测试集。",
        }
    if eval_fn is None:
        findings.append(
            _finding(
                "model_test",
                "major",
                "未提供评测函数（eval_fn），评分卡为 pending，不含任何分数。",
                "人工评分或注入评测函数后重跑；缺评测即 pending，绝不伪造分数。",
            )
        )
        pending_items = []
        for item in items:
            grade, _ = _item_evidence(item["id"], evidence_grades)
            pending_items.append(
                {"kind": item["kind"], "id": item["id"], "label": item["label"],
                 "status": "pending", "scores": None, "evidence_grade": grade}
            )
        summary: dict[str, int] = {}
        for entry in pending_items:
            summary[entry["evidence_grade"]] = (
                summary.get(entry["evidence_grade"], 0) + 1
            )
        return {
            "composition": {**counts, "total_items": total},
            "dimension_means": None,
            "overall_mean": None,
            "items": pending_items,
            "release_conditions": [
                {"condition": "测试集非空", "met": True},
                {"condition": "全部测试项均已评分", "met": False},
                {
                    "condition": f"四项均值均 >= {threshold:g}",
                    "met": False,
                },
                {"condition": "证据等级无不确定项", "met": True},
            ],
            "confirmation_gates": _confirmation_gates(
                direction_ok, counts, "pending"
            ),
            "evidence_summary": summary,
            "released": False,
            "status": "pending",
            "release_threshold": threshold,
            "findings": findings,
            "recommendation": "不放行批量：待评测，先给测试集评分。",
        }
    if not callable(eval_fn):
        raise CapabilityError("story.model_test: eval_fn must be callable")
    for item in items:
        grade, _ = _item_evidence(item["id"], evidence_grades)
        try:
            raw_scores = eval_fn(item["kind"], item)
        except Exception as exc:  # judge failure is data, not a crash
            errored += 1
            scored_items.append(
                {
                    "kind": item["kind"],
                    "id": item["id"],
                    "label": item["label"],
                    "status": "error",
                    "scores": None,
                    "evidence_grade": grade,
                    "error": f"评测函数报错：{exc}",
                }
            )
            continue
        scores, error = _validate_scores(raw_scores)
        if error is not None:
            errored += 1
            scored_items.append(
                {
                    "kind": item["kind"],
                    "id": item["id"],
                    "label": item["label"],
                    "status": "error",
                    "scores": None,
                    "evidence_grade": grade,
                    "error": error,
                }
            )
            continue
        scored_items.append(
            {
                "kind": item["kind"],
                "id": item["id"],
                "label": item["label"],
                "status": "scored",
                "scores": scores,
                "evidence_grade": grade,
            }
        )
    if errored:
        findings.append(
            _finding(
                "model_test",
                "blocker",
                f"{errored} 项评测不完整（报错或缺分/超范围），评分不完整，不放行。",
                "修复评测函数对这几项的输出（四项齐全、0-10 分）后重跑。",
            )
        )
    scored_only = [i for i in scored_items if i["status"] == "scored"]
    dimension_means: dict[str, dict[str, Any]] | None = None
    overall_mean: float | None = None
    if scored_only:
        dimension_means = {}
        means: list[float] = []
        for key, label in DIMENSIONS:
            mean = sum(i["scores"][key] for i in scored_only) / len(scored_only)
            mean = round(mean, 3)
            means.append(mean)
            dimension_means[key] = {
                "label": label,
                "mean": mean,
                "threshold": threshold,
                "met": mean >= threshold,
            }
        overall_mean = round(sum(means) / len(means), 3)
    all_scored = errored == 0
    dims_met = bool(dimension_means) and all(
        entry["met"] for entry in dimension_means.values()
    )
    # Evidence rule: an uncertain-graded scored item blocks release,
    # however good its numbers look -- numbers on uncertain evidence
    # are not a pass. Unsupplied grades do not block (backward
    # compatible with plain scorecard calls).
    uncertain_ids = [
        entry["id"]
        for entry in scored_items
        if entry["status"] == "scored" and entry["evidence_grade"] == "uncertain"
    ]
    evidence_blocked = len(uncertain_ids) > 0
    if errored:
        pilot_status = "pending"
    elif dims_met:
        pilot_status = "passed"
    else:
        pilot_status = "failed"
    gates = _confirmation_gates(direction_ok, counts, pilot_status)
    gates_ok = all(g["status"] == "passed" for g in gates)
    conditions = [
        {"condition": "测试集非空", "met": True},
        {"condition": "全部测试项均已评分", "met": all_scored},
        {"condition": f"四项均值均 >= {threshold:g}", "met": dims_met},
        {"condition": "证据等级无不确定项", "met": not evidence_blocked},
    ]
    if require_confirmation_gates:
        conditions.append({"condition": "四级确认门全过", "met": gates_ok})
    released = all(c["met"] for c in conditions)
    summary: dict[str, int] = {}
    for entry in scored_items:
        summary[entry["evidence_grade"]] = (
            summary.get(entry["evidence_grade"], 0) + 1
        )
    if errored:
        status = "pending"
        recommendation = "不放行批量：评分不完整，先修评测再重跑。"
    elif released:
        status = "released"
        recommendation = (
            f"放行批量：测试集 {total} 项、四项均值均 >= {threshold:g}，"
            f"总均分 {overall_mean}。"
        )
    else:
        status = "not_released"
        reasons: list[str] = []
        if dimension_means and not dims_met:
            failed = [
                dimension_means[key]["label"]
                for key, _ in DIMENSIONS
                if not dimension_means[key]["met"]
            ]
            findings.append(
                _finding(
                    "model_test",
                    "major",
                    f"未达放行线（{threshold:g}）的维度：{', '.join(failed)}。",
                    "先调模型/提示词对未达标维度重测，达标前不进批量。",
                )
            )
            reasons.append("未达标维度：" + ", ".join(failed))
        if evidence_blocked:
            findings.append(
                _finding(
                    "model_test",
                    "major",
                    f"证据等级为不确定项：{', '.join(uncertain_ids)}，"
                    "不确定证据上的分数不能放行。",
                    "复核这几项的证据，确认为已观察或用户指定后重跑。",
                )
            )
            reasons.append("证据不确定项：" + ", ".join(uncertain_ids))
        if require_confirmation_gates and not gates_ok:
            open_gates = [
                g["label"] for g in gates if g["status"] != "passed"
            ]
            findings.append(
                _finding(
                    "model_test",
                    "major",
                    f"四级确认门未全过：{', '.join(open_gates)}。",
                    "补齐未过的确认门（方向确认、核心资产、试点镜）后重跑。",
                )
            )
            reasons.append("确认门未全过：" + ", ".join(open_gates))
        if pilot_status == "failed":
            reasons.append("试点镜未过，不批量")
        recommendation = (
            "不放行批量："
            + "；".join(reasons)
            + "；达标前不进批量。"
        )
    return {
        "composition": {**counts, "total_items": total},
        "dimension_means": dimension_means,
        "overall_mean": overall_mean,
        "items": scored_items,
        "release_conditions": conditions,
        "confirmation_gates": gates,
        "evidence_summary": summary,
        "released": released,
        "status": status,
        "release_threshold": threshold,
        "findings": findings,
        "recommendation": recommendation,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "test_set": {"type": "object"},
        "release_threshold": {"type": "number"},
        "threshold": {"type": "number"},
        "evidence_grades": {"type": "object"},
        "direction": {"type": ["object", "boolean"]},
        "require_confirmation_gates": {"type": "boolean"},
        # eval_fn is a Python-level injected callable (the evaluator),
        # not a JSON value: it is whitelisted here with no type
        # constraint so additionalProperties: False does not reject
        # the legitimate injection path used by _render.
        "eval_fn": {},
    },
    "required": ["test_set"],
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "model_test.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    eval_fn = params.get("eval_fn")
    threshold = params.get("release_threshold", params.get("threshold", DEFAULT_RELEASE_THRESHOLD))
    payload = build_scorecard(
        params.get("test_set"),
        eval_fn=eval_fn if callable(eval_fn) else None,
        release_threshold=threshold,
        evidence_grades=params.get("evidence_grades"),
        direction=params.get("direction"),
        require_confirmation_gates=bool(
            params.get("require_confirmation_gates", False)
        ),
    )
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_model_test_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.model_test",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "批量前模型测试：代表性人物/场景/关键镜头测试集 → 模型"
                "评分卡（质感、光线自然度、人物一致性、动作准确度四项＋"
                "总评＋是否放行批量；试点镜不过不批量）。评分卡本身不调"
                "任何生成 API，分数由人工或注入的评测函数给；缺评测即"
                " pending，绝不伪造分数；评分卡含测试集构成、放行条件、"
                "四级确认门（方向、核心资产、试点镜、交付）与事实分级"
                "证据规则（已观察／不确定／用户指定，不确定证据挡放行）。"
            ),
            line="model_test",
        )
    )
    return ["story.model_test"]


register_model_test_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.model_test on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
