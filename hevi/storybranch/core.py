"""Plot-line forecasting (clean-room original implementation).

多线推演: before writing the next chapter/section, generate 2-5 isolated
future branches from the current story state (canon facts, characters,
recent chapter summaries, author intent). Each branch carries beats, key
character decisions, estimated state changes, risks, and an intent-match
score (0-1). Branches can be compared side by side; adopting one writes a
``branch_plan`` file while the canon itself is never modified. When the
canon story state changes, the old forecast is marked stale via its story
hash.

This module is pure logic: no network, no LLM calls, no hevi imports.
LLM generation is an *injectable* function parameter (``generator_fn``);
the bundled default is a deterministic local placeholder so the pipeline
works (and tests run) with zero cost and zero network.

Note on provenance: this was designed from the functional definition in
the task brief. InkOS is AGPL-3.0 and was NOT consulted -- no InkOS code,
prompts, or SKILL.md were read or reproduced here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Branch",
    "Forecast",
    "GeneratorFn",
    "StoryState",
    "adopt_branch",
    "build_comparison",
    "compute_story_hash",
    "default_generator",
    "forecast_branches",
    "is_stale",
    "load_branch_plan",
    "load_forecast",
    "normalize_state",
    "placeholder_generator",
    "save_branch_plan",
    "save_forecast",
    "staleness_report",
    "validate_branch_payload",
    "verify_forecast_file",
]

MIN_BRANCHES = 2
MAX_BRANCHES = 5

# Signature: (state_dict, branch_count, seed) -> list of branch payloads.
GeneratorFn = Callable[[dict[str, Any], int, int], list[Any]]

_REQUIRED_BRANCH_FIELDS = (
    "beats",
    "key_decisions",
    "state_changes",
    "risks",
    "intent_match",
)


# ---------------------------------------------------------------------------
# Story state
# ---------------------------------------------------------------------------


@dataclass
class StoryState:
    """Current story state used as the forecast input."""

    canon_facts: list[str] = field(default_factory=list)
    characters: list[Any] = field(default_factory=list)
    recent_summaries: list[str] = field(default_factory=list)
    author_intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "canon_facts": list(self.canon_facts),
            "characters": copy.deepcopy(self.characters),
            "recent_summaries": list(self.recent_summaries),
            "author_intent": self.author_intent,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StoryState:
        if not isinstance(payload, dict):
            raise ValueError("story state must be a dict")
        return cls(
            canon_facts=list(payload.get("canon_facts") or []),
            characters=list(payload.get("characters") or []),
            recent_summaries=list(payload.get("recent_summaries") or []),
            author_intent=str(payload.get("author_intent") or ""),
        )


def normalize_state(state: StoryState | dict[str, Any]) -> StoryState:
    if isinstance(state, StoryState):
        return state
    if isinstance(state, dict):
        return StoryState.from_dict(state)
    raise ValueError(f"story state must be StoryState or dict, got {type(state).__name__}")


def _canonical_story_dict(state: StoryState) -> dict[str, Any]:
    payload = state.to_dict()
    payload["canon_facts"] = [str(x) for x in payload["canon_facts"]]
    payload["recent_summaries"] = [str(x) for x in payload["recent_summaries"]]
    return payload


def compute_story_hash(state: StoryState | dict[str, Any]) -> str:
    """Stable sha256 of the current story state (canon facts etc.).

    Any change to the canon facts / characters / summaries / intent changes
    the hash, which is what makes old forecasts stale.
    """
    normalized = normalize_state(state)
    canonical = json.dumps(
        _canonical_story_dict(normalized),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Branch data
# ---------------------------------------------------------------------------


@dataclass
class Branch:
    """One isolated future branch."""

    branch_id: str
    title: str
    beats: list[str]
    key_decisions: list[Any]
    state_changes: list[Any]
    risks: list[str]
    intent_match: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "title": self.title,
            "beats": list(self.beats),
            "key_decisions": copy.deepcopy(self.key_decisions),
            "state_changes": copy.deepcopy(self.state_changes),
            "risks": list(self.risks),
            "intent_match": float(self.intent_match),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, index: int = 0) -> Branch:
        normalized = validate_branch_payload(payload, index=index)
        return cls(**normalized)


def validate_branch_payload(payload: Any, *, index: int = 0) -> dict[str, Any]:
    """Validate one generator-produced branch payload; return normalized fields.

    Raises ValueError on any missing/invalid field.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"branch #{index}: payload must be a dict")
    missing = [f for f in _REQUIRED_BRANCH_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"branch #{index}: missing fields: {missing}")

    branch_id = str(payload.get("branch_id") or f"branch-{index + 1}")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError(f"branch #{index} ({branch_id}): 'title' is required")

    def _str_list(value: Any, name: str) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValueError(
                f"branch #{index} ({branch_id}): '{name}' must be a non-empty list"
            )
        items = [str(x).strip() for x in value]
        if any(not x for x in items):
            raise ValueError(
                f"branch #{index} ({branch_id}): '{name}' must not contain empty items"
            )
        return items

    beats = _str_list(payload["beats"], "beats")
    risks = _str_list(payload["risks"], "risks")

    key_decisions = payload["key_decisions"]
    if not isinstance(key_decisions, list) or not key_decisions:
        raise ValueError(
            f"branch #{index} ({branch_id}): 'key_decisions' must be a non-empty list"
        )
    state_changes = payload["state_changes"]
    if not isinstance(state_changes, list) or not state_changes:
        raise ValueError(
            f"branch #{index} ({branch_id}): 'state_changes' must be a non-empty list"
        )

    try:
        intent_match = float(payload["intent_match"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"branch #{index} ({branch_id}): 'intent_match' must be a number in [0, 1]"
        ) from exc
    if not 0.0 <= intent_match <= 1.0:
        raise ValueError(
            f"branch #{index} ({branch_id}): 'intent_match' must be in [0, 1], "
            f"got {payload['intent_match']!r}"
        )

    return {
        "branch_id": branch_id,
        "title": title,
        "beats": beats,
        "key_decisions": copy.deepcopy(key_decisions),
        "state_changes": copy.deepcopy(state_changes),
        "risks": risks,
        "intent_match": intent_match,
    }


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------


def build_comparison(branches: list[Branch]) -> dict[str, Any]:
    """Build the lateral comparison table structure for a set of branches."""
    rows = [
        {
            "branch_id": b.branch_id,
            "title": b.title,
            "beat_count": len(b.beats),
            "key_decision_count": len(b.key_decisions),
            "state_change_count": len(b.state_changes),
            "risk_count": len(b.risks),
            "risks": list(b.risks),
            "intent_match": float(b.intent_match),
            "beats": list(b.beats),
            "key_decisions": copy.deepcopy(b.key_decisions),
            "state_changes": copy.deepcopy(b.state_changes),
        }
        for b in branches
    ]
    ranking = sorted(rows, key=lambda r: (-r["intent_match"], r["branch_id"]))
    risk_ranking = sorted(rows, key=lambda r: (-r["risk_count"], r["branch_id"]))
    return {
        "columns": [
            "branch_id",
            "title",
            "beat_count",
            "key_decision_count",
            "state_change_count",
            "risk_count",
            "intent_match",
        ],
        "rows": rows,
        "intent_match_ranking": [r["branch_id"] for r in ranking],
        "best_branch_id": ranking[0]["branch_id"] if ranking else None,
        "highest_risk_branch_id": risk_ranking[0]["branch_id"] if risk_ranking else None,
        "branch_count": len(rows),
    }


# ---------------------------------------------------------------------------
# Default (local, deterministic, zero-cost) generator
# ---------------------------------------------------------------------------


_PLACEHOLDER_ANGLES = [
    ("正面推进", "让核心冲突按作者意图直接向前推进一步,冲突升级但人物关系保持稳定。"),
    ("代价反转", "主角为推进目标付出意外代价,揭示先前决定的隐藏成本。"),
    ("新信息揭露", "一条被埋藏的正史事实浮出水面,迫使所有人重新评估立场。"),
    ("关系转折", "关键人物之间发生立场或情感的转折,同盟重组。"),
    ("延迟揭示", "把最大的揭示推迟一章,用悬念钩子收尾,为下下章蓄力。"),
]


def _character_names(characters: list[Any]) -> list[str]:
    names: list[str] = []
    for c in characters:
        name = (c.get("name") or c.get("id") or "") if isinstance(c, dict) else str(c)
        name = name.strip()
        if name:
            names.append(name)
    return names or ["主角"]


def placeholder_generator(
    state_dict: dict[str, Any], branch_count: int, seed: int
) -> list[dict[str, Any]]:
    """Deterministic local placeholder generator (no LLM, no network).

    Produces clearly-labeled placeholder branches derived from the story
    state and seed. Real deployments inject an LLM-backed ``generator_fn``;
    this one exists so the pipeline is runnable and testable offline.
    """
    state = StoryState.from_dict(state_dict)
    names = _character_names(state.characters)
    anchor = (state.canon_facts[0] if state.canon_facts else "当前正史")
    recent = state.recent_summaries[-1] if state.recent_summaries else "最近章节"
    intent = state.author_intent or "作者意图未指定"

    rng_state = hashlib.sha256(
        f"{compute_story_hash(state)}:{branch_count}:{seed}".encode()
    ).hexdigest()

    branches: list[dict[str, Any]] = []
    for i in range(branch_count):
        angle, angle_desc = _PLACEHOLDER_ANGLES[i % len(_PLACEHOLDER_ANGLES)]
        hero = names[i % len(names)]
        digest = int(hashlib.sha256(f"{rng_state}:{i}".encode()).hexdigest()[:8], 16)
        # Deterministic intent-match ladder, jittered by digest.
        intent_match = round(max(0.35, min(0.95, 0.92 - i * 0.09 + (digest % 7) * 0.01)), 2)
        branches.append(
            {
                "branch_id": f"branch-{i + 1}",
                "title": f"[占位分支] {angle}（{hero}）",
                "beats": [
                    f"承接「{recent}」: {hero} 面对「{anchor}」做出新的抉择。",
                    f"{angle}展开: {angle_desc}",
                    f"收束钩子: 与作者意图「{intent}」呼应的悬念落点。",
                ],
                "key_decisions": [
                    {"character": hero, "decision": f"按「{angle}」方向采取行动"},
                    {
                        "character": names[(i + 1) % len(names)],
                        "decision": "对主角的行动做出回应,立场发生位移",
                    },
                ],
                "state_changes": [
                    f"预计状态变化: {angle}导致的人物关系/局势位移（占位描述）",
                    "预计状态变化: 为下一章埋下可回收的伏笔",
                ],
                "risks": [
                    "占位生成器未接入真实 LLM,节拍细节需要人工/LLM 重写",
                    f"「{angle}」方向若与伏笔冲突,需回查正史一致性",
                ],
                "intent_match": intent_match,
            }
        )
    return branches


default_generator = placeholder_generator


# ---------------------------------------------------------------------------
# Forecast orchestration
# ---------------------------------------------------------------------------


@dataclass
class Forecast:
    """A generated set of isolated future branches for one story state."""

    story_hash: str
    story_state: dict[str, Any]
    branches: list[Branch]
    comparison: dict[str, Any]
    branch_count: int
    seed: int
    generator: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "hevi.storybranch.forecast/v1",
            "story_hash": self.story_hash,
            "story_state": copy.deepcopy(self.story_state),
            "branch_count": self.branch_count,
            "seed": self.seed,
            "generator": self.generator,
            "branches": [b.to_dict() for b in self.branches],
            "comparison": copy.deepcopy(self.comparison),
            "stale": False,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Forecast:
        if not isinstance(payload, dict):
            raise ValueError("forecast payload must be a dict")
        branches = [
            Branch.from_dict(b, index=i) for i, b in enumerate(payload.get("branches") or [])
        ]
        if not (MIN_BRANCHES <= len(branches) <= MAX_BRANCHES):
            raise ValueError(
                f"forecast must contain {MIN_BRANCHES}-{MAX_BRANCHES} branches, "
                f"got {len(branches)}"
            )
        ids = [b.branch_id for b in branches]
        if len(set(ids)) != len(ids):
            raise ValueError(f"forecast branch_ids must be unique, got {ids}")
        return cls(
            story_hash=str(payload.get("story_hash") or ""),
            story_state=copy.deepcopy(payload.get("story_state") or {}),
            branches=branches,
            comparison=copy.deepcopy(payload.get("comparison") or build_comparison(branches)),
            branch_count=int(payload.get("branch_count") or len(branches)),
            seed=int(payload.get("seed") or 0),
            generator=str(payload.get("generator") or "unknown"),
        )


def _validate_branch_count(branch_count: Any) -> int:
    if isinstance(branch_count, bool):
        raise ValueError("branch_count must be an integer")
    try:
        n = int(branch_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("branch_count must be an integer") from exc
    if not MIN_BRANCHES <= n <= MAX_BRANCHES:
        raise ValueError(
            f"branch_count must be between {MIN_BRANCHES} and {MAX_BRANCHES}, got {n}"
        )
    return n


def forecast_branches(
    state: StoryState | dict[str, Any],
    branch_count: int = 3,
    generator_fn: GeneratorFn | None = None,
    seed: int = 42,
    *,
    generator_name: str | None = None,
) -> Forecast:
    """Generate 2-5 isolated future branches for the given story state.

    ``generator_fn`` is the injectable LLM hook with signature
    ``(state_dict, branch_count, seed) -> list[branch payloads]``.
    When omitted, the deterministic local placeholder generator is used
    (zero cost, zero network).

    Raises ValueError on invalid input or malformed generator output.
    """
    normalized = normalize_state(state)
    if not normalized.author_intent.strip():
        raise ValueError("author_intent is required (non-empty)")
    n = _validate_branch_count(branch_count)

    gen = generator_fn or default_generator
    gen_name = generator_name or getattr(gen, "__name__", "custom")

    try:
        raw = gen(normalized.to_dict(), n, int(seed))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"generator_fn raised: {exc}") from exc

    if not isinstance(raw, list):
        raise ValueError("generator_fn must return a list of branch payloads")
    if len(raw) != n:
        raise ValueError(
            f"generator_fn returned {len(raw)} branches but {n} were requested"
        )

    branches = [Branch.from_dict(payload, index=i) for i, payload in enumerate(raw)]
    ids = [b.branch_id for b in branches]
    if len(set(ids)) != len(ids):
        raise ValueError(f"generator_fn produced duplicate branch_ids: {ids}")

    return Forecast(
        story_hash=compute_story_hash(normalized),
        story_state=normalized.to_dict(),
        branches=branches,
        comparison=build_comparison(branches),
        branch_count=n,
        seed=int(seed),
        generator=gen_name,
    )


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _hash_of(value: StoryState | dict[str, Any] | str) -> str:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("story hash string must be non-empty")
        return value.strip()
    return compute_story_hash(value)


def is_stale(
    forecast: Forecast | dict[str, Any],
    current: StoryState | dict[str, Any] | str,
) -> bool:
    """True when the canon story state changed since the forecast was made."""
    stored = forecast.story_hash if isinstance(forecast, Forecast) else str(
        forecast.get("story_hash") or ""
    )
    if not stored:
        raise ValueError("forecast has no story_hash")
    return stored != _hash_of(current)


def staleness_report(
    forecast: Forecast | dict[str, Any],
    current: StoryState | dict[str, Any] | str,
) -> dict[str, Any]:
    """Describe whether a forecast is stale against the current story state."""
    stored = forecast.story_hash if isinstance(forecast, Forecast) else str(
        forecast.get("story_hash") or ""
    )
    current_hash = _hash_of(current)
    stale = stored != current_hash
    return {
        "stale": stale,
        "forecast_story_hash": stored,
        "current_story_hash": current_hash,
        "branch_count": len(forecast.branches)
        if isinstance(forecast, Forecast)
        else len(forecast.get("branches") or []),
    }


# ---------------------------------------------------------------------------
# Persistence (forecast + branch plan)
# ---------------------------------------------------------------------------


def save_forecast(forecast: Forecast | dict[str, Any], path: str | Path) -> Path:
    payload = forecast.to_dict() if isinstance(forecast, Forecast) else forecast
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_forecast(path: str | Path) -> Forecast:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"forecast file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"forecast file is not valid JSON: {path}: {exc}") from exc
    return Forecast.from_dict(payload)


def verify_forecast_file(path: str | Path) -> dict[str, Any]:
    """Verify a forecast artifact: exists, parses, holds 2-5 valid branches.

    Returns the staleness-relevant summary. Raises FileNotFoundError /
    ValueError when the artifact is missing or broken -- this is what the
    "delete the artifact, the check must fail" contract test exercises.
    """
    forecast = load_forecast(path)
    return {
        "ok": True,
        "path": str(path),
        "story_hash": forecast.story_hash,
        "branch_count": len(forecast.branches),
        "branch_ids": [b.branch_id for b in forecast.branches],
        "has_comparison": bool(forecast.comparison.get("rows")),
    }


def _read_bytes(path: str | Path | None) -> bytes | None:
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"canon file not found: {p}")
    return p.read_bytes()


def adopt_branch(
    forecast: Forecast | dict[str, Any] | str | Path,
    branch_id: str,
    plan_path: str | Path,
    *,
    canon_path: str | Path | None = None,
) -> dict[str, Any]:
    """Adopt one branch into a plan file; the canon itself is never modified.

    When ``canon_path`` is given, the canon file's bytes are hashed before
    and after writing the plan; if they differ (something else touched the
    canon mid-adopt) a ValueError is raised instead of returning silently.
    """
    if isinstance(forecast, (str, Path)):
        loaded = load_forecast(forecast)
    elif isinstance(forecast, Forecast):
        loaded = forecast
    elif isinstance(forecast, dict):
        loaded = Forecast.from_dict(forecast)
    else:
        raise ValueError(f"unsupported forecast input: {type(forecast).__name__}")

    if not str(branch_id or "").strip():
        raise ValueError("branch_id is required")
    match = [b for b in loaded.branches if b.branch_id == branch_id]
    if not match:
        known = [b.branch_id for b in loaded.branches]
        raise ValueError(f"branch_id {branch_id!r} not found in forecast; known: {known}")
    branch = match[0]

    canon_before = _read_bytes(canon_path)

    plan: dict[str, Any] = {
        "format": "hevi.storybranch.branch_plan/v1",
        "adopted_branch_id": branch.branch_id,
        "branch": branch.to_dict(),
        "story_hash": loaded.story_hash,
        "story_state": copy.deepcopy(loaded.story_state),
        "comparison": copy.deepcopy(loaded.comparison),
        "status": "adopted",
        # Explicit guarantee: adopting a branch writes only the plan file.
        "canon_modified": False,
    }
    plan_path = Path(plan_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if canon_path is not None:
        canon_after = _read_bytes(canon_path)
        if canon_after != canon_before:
            raise ValueError(
                f"canon file changed during adopt: {canon_path} "
                "(the canon must not be modified by adopting a branch)"
            )
        plan["canon_sha256_before"] = hashlib.sha256(canon_before).hexdigest()

    return plan


save_branch_plan = adopt_branch


def load_branch_plan(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"branch plan file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"branch plan is not valid JSON: {path}: {exc}") from exc
    if payload.get("format") != "hevi.storybranch.branch_plan/v1":
        raise ValueError(f"not a branch_plan file: {path}")
    if not payload.get("adopted_branch_id") or not payload.get("branch"):
        raise ValueError(f"branch plan is missing the adopted branch: {path}")
    return payload
