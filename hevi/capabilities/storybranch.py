"""Plot-line forecasting capabilities (original clean-room implementation).

Registers two ``hevi.capabilities`` entries under the CAPABILITY_CONTRACT
(precedent: ``hevi.capabilities.multimodel``):

* ``story.branch_forecast`` -- given the current story state (canon facts,
  characters, recent chapter summaries, author intent), generate 2-5
  isolated future branches *before* writing the next chapter/section.
  Each branch carries beats, key character decisions, estimated state
  changes, risks, and an intent-match score (0-1), plus a lateral
  comparison table. Writes ``branches.json``. Canon is read-only here.

* ``story.branch_adopt`` -- adopt one branch from a ``branches.json``
  into a plan file (``branch_plan.json`` in ``out_dir``). The canon file,
  when supplied via ``canon_path``, is hashed before/after and must be
  unchanged -- adopting is writing a *plan*, never editing the canon.

LLM generation is injectable: see
``hevi.storybranch.core.forecast_branches(generator_fn=...)`` and the
module hook :func:`set_generator_fn`. Generator resolution order: an
explicitly injected generator wins; otherwise the default Monid backend
(:mod:`hevi.llm.monid_chat`, gpt-4o-mini via blockrun — the same route and
the same ``MONID_API_KEY`` env key as ``story.film_from_prompt``, billed
per Monid call at a small per-call rate) is used when the key is
resolvable; with no key the deterministic local placeholder generator in
``hevi.storybranch.core`` runs instead (zero paid calls, zero network) —
behavior is then exactly the pre-default-backend behavior, and
``qa['generator']`` always names what actually ran.

Staleness: every forecast stores ``story_hash`` (hash of the story state).
When the canon changes, the hash changes and ``story.branch_adopt``
refuses a mismatched ``current_story_hash`` unless ``allow_stale`` is set,
while core ``is_stale()`` lets callers check without adopting.

Provenance note: InkOS is AGPL-3.0; this module was written from the
functional definition only -- no InkOS code/prompts/SKILL.md were read.
"""

from __future__ import annotations

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

# Injectable generator hook. None -> default resolution (Monid backend when
# its key is resolvable, else the core's local placeholder).
# Signature: (state_dict, branch_count, seed) -> list[branch payloads].
_generator_fn = None

# Generator name reported in qa for the default Monid backend.
_DEFAULT_GENERATOR_NAME = "monid_gpt-4o-mini"


def set_generator_fn(fn) -> None:
    """Inject the branch generator used by ``story.branch_forecast``.

    Pass ``None`` to restore the default resolution (Monid backend when
    available, otherwise the deterministic local placeholder). Tests
    inject a fake generator this way (or via monkeypatching
    ``_generator_fn``); production may inject an LLM-backed callable.
    """
    global _generator_fn
    _generator_fn = fn


def get_generator_fn():
    """Return the explicitly injected generator (``None`` if none).

    Note this does not reflect the default Monid backend; renders resolve
    the effective generator via :func:`_resolve_generator`.
    """
    return _generator_fn


def _default_generator_fn(state_dict, branch_count, seed):
    """Default backend: Monid gpt-4o-mini chat (see hevi.llm.monid_chat).

    Returns branch payloads in exactly the shape the core placeholder
    generator returns (validated downstream by ``forecast_branches``).
    """
    from hevi.llm import monid_chat

    return monid_chat.generate_branches_sync(state_dict, branch_count, seed)


def _resolve_generator():
    """Effective (generator_fn, generator_name) for a forecast render.

    Injected generator wins; else the default Monid backend when its key
    is resolvable; else ``(None, None)`` — the core then falls back to
    its deterministic local placeholder, unchanged from before.
    """
    if _generator_fn is not None:
        return _generator_fn, getattr(_generator_fn, "__name__", "injected")
    from hevi.llm import monid_chat

    if monid_chat.monid_key_available():
        return _default_generator_fn, _DEFAULT_GENERATOR_NAME
    return None, None


def _story_state_from_params(params: dict[str, Any]):
    from hevi.storybranch.core import StoryState

    return StoryState(
        canon_facts=list(params.get("canon_facts") or []),
        characters=list(params.get("characters") or []),
        recent_summaries=list(params.get("recent_summaries") or []),
        author_intent=str(params.get("author_intent") or ""),
    )


def _render_branch_forecast(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storybranch import core as branch_core

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    state = _story_state_from_params(params)
    if not state.author_intent.strip():
        raise CapabilityError("story.branch_forecast: 'author_intent' is required")
    branch_count = params.get("branch_count", 3)

    effective_fn, effective_name = _resolve_generator()
    try:
        forecast_obj = branch_core.forecast_branches(
            state,
            branch_count=branch_count,
            generator_fn=effective_fn,
            seed=int(seed),
            generator_name=effective_name,
        )
    except ValueError as exc:
        raise CapabilityError(f"story.branch_forecast: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"story.branch_forecast failed: {exc}") from exc

    branches_path = branch_core.save_forecast(forecast_obj, out_dir / "branches.json")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(branches_path),
        qa={
            "branches_json": str(branches_path),
            "branch_count": len(forecast_obj.branches),
            "branch_ids": [b.branch_id for b in forecast_obj.branches],
            "story_hash": forecast_obj.story_hash,
            "stale": False,
            "generator": forecast_obj.generator,
            "comparison": forecast_obj.comparison,
            "note": (
                "Forecast only: branches are isolated proposals. "
                "Canon is not modified; adopt via story.branch_adopt."
            ),
        },
    )


def _render_branch_adopt(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storybranch import core as branch_core

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    branches_path = Path(str(params["branches_path"]))
    branch_id = str(params["branch_id"])
    canon_path = params.get("canon_path")
    current_hash = params.get("current_story_hash")
    allow_stale = bool(params.get("allow_stale", False))

    if not branches_path.is_file():
        raise CapabilityError(
            f"story.branch_adopt: branches file not found: {branches_path}"
        )
    try:
        forecast_obj = branch_core.load_forecast(branches_path)
    except (FileNotFoundError, ValueError) as exc:
        raise CapabilityError(f"story.branch_adopt: {exc}") from exc

    stale = False
    if current_hash:
        stale = branch_core.is_stale(forecast_obj, str(current_hash))
        if stale and not allow_stale:
            raise CapabilityError(
                "story.branch_adopt: forecast is stale "
                f"(forecast story_hash={forecast_obj.story_hash}, "
                f"current_story_hash={current_hash}); re-run "
                "story.branch_forecast or pass allow_stale=true"
            )

    plan_path = out_dir / "branch_plan.json"
    try:
        plan = branch_core.adopt_branch(
            forecast_obj,
            branch_id,
            plan_path,
            canon_path=Path(canon_path) if canon_path else None,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise CapabilityError(f"story.branch_adopt: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"story.branch_adopt failed: {exc}") from exc

    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(plan_path),
        qa={
            "branch_plan_json": str(plan_path),
            "adopted_branch_id": plan["adopted_branch_id"],
            "branch_count": len(forecast_obj.branches),
            "story_hash": forecast_obj.story_hash,
            "stale": stale,
            "canon_modified": False,
            "canon_path": str(canon_path) if canon_path else None,
            "note": (
                "Adoption writes only branch_plan.json; the canon "
                "itself is never modified by this capability."
            ),
        },
    )


def register_storybranch_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="story.branch_forecast",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "canon_facts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Current canon facts (positive facts only)",
                    },
                    "characters": {
                        "type": "array",
                        "items": {},
                        "description": "Characters (strings or {name, ...} dicts)",
                    },
                    "recent_summaries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recent chapter/section summaries",
                    },
                    "author_intent": {
                        "type": "string",
                        "minLength": 1,
                        "description": "What the author wants the next part to achieve",
                    },
                    "branch_count": {
                        "type": "integer",
                        "minimum": 2,
                        "maximum": 5,
                        "default": 3,
                        "description": "Number of isolated future branches (2-5)",
                    },
                },
                "required": ["author_intent"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.1,
            render=_render_branch_forecast,
            description=(
                "Plot-line forecasting before writing: from the current "
                "story state (canon facts, characters, recent summaries, "
                "author intent) generate 2-5 isolated future branches, "
                "each with beats, key character decisions, estimated "
                "state changes, risks and an intent-match score (0-1), "
                "plus a lateral comparison table. Writes branches.json "
                "with the story-state hash for staleness detection. "
                "Generator is injectable (set_generator_fn wins); "
                "otherwise the default Monid gpt-4o-mini backend runs "
                "when MONID_API_KEY is available (per-call small fee), "
                "and without a key the deterministic local placeholder "
                "runs instead (no LLM, no network, no cost). "
                "qa['generator'] always names what ran."
            ),
            line="storybranch",
        )
    )
    registered.append("story.branch_forecast")

    register(
        Capability(
            name="story.branch_adopt",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "branches_path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Path to branches.json from story.branch_forecast",
                    },
                    "branch_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The branch to adopt, e.g. 'branch-2'",
                    },
                    "canon_path": {
                        "type": "string",
                        "description": (
                            "Optional canon file to guard: hashed before/after; "
                            "adoption must leave it byte-identical"
                        ),
                    },
                    "current_story_hash": {
                        "type": "string",
                        "description": (
                            "Optional current story-state hash; a mismatch "
                            "marks the forecast stale and blocks adoption"
                        ),
                    },
                    "allow_stale": {
                        "type": "boolean",
                        "default": False,
                        "description": "Adopt even when the forecast is stale",
                    },
                },
                "required": ["branches_path", "branch_id"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.05,
            render=_render_branch_adopt,
            description=(
                "Adopt one forecasted branch into a plan file "
                "(branch_plan.json): stores the adopted branch, its "
                "story hash and the comparison table. The canon itself "
                "is never modified; a supplied canon_path is verified "
                "byte-identical before/after. Stale forecasts (story "
                "hash mismatch) are refused unless allow_stale is set."
            ),
            line="storybranch",
        )
    )
    registered.append("story.branch_adopt")

    return registered
