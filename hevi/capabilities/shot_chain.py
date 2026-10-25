"""Shot chaining -- ``story.shot_chain``.

Links one episode's shots into a playback-order chain so consecutive
shots stay visually continuous. The rule is deliberately narrow and
mechanical: every shot after the first carries a tail-frame reference
pointing at the immediately preceding shot, and the first shot carries
none. A caller-supplied first-frame reference, when given for a shot,
is attached to that shot's link verbatim and is never invented for
shots that have none.

This capability never generates media, never reorders shots, and
never calls any generation API: it only arranges references the
caller already has. Input order is broadcast order, full stop.

Method note (own wording): the continuity device here is "the next
shot starts from the previous shot's last frame" plus an optional
per-shot first-frame reference supplied by the caller. Nothing about
how a frame is rendered, sampled, or scored lives in this module.
"""

from __future__ import annotations

import copy
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

__all__ = ["build_chain", "validate_chain"]


def _lookup_first_frame_ref(first_frame_refs: Any, shot_id: Any) -> Any:
    """Return the caller-supplied first-frame ref for one shot, or None."""
    if first_frame_refs is None:
        return None
    if isinstance(first_frame_refs, dict):
        value = first_frame_refs.get(shot_id)
        return copy.deepcopy(value) if value is not None else None
    if isinstance(first_frame_refs, list):
        for item in first_frame_refs:
            if not isinstance(item, dict):
                continue
            if item.get("shot_id") != shot_id:
                continue
            if "first_frame_ref" in item:
                value = item["first_frame_ref"]
            elif "ref" in item:
                value = item["ref"]
            else:
                return None
            return copy.deepcopy(value) if value is not None else None
    return None


def build_chain(shots: Any, *, first_frame_refs: Any = None) -> dict[str, Any]:
    """Build the tail-frame chain for ``shots``, in input order.

    ``shots`` is a list of shot dicts in broadcast order; each must
    carry a non-empty ``shot_id``. The returned dict has one key,
    ``chain``: one link per shot, in the same order, each with
    ``shot_id``, ``prev_shot_id`` (None for the first shot),
    ``tail_frame_ref`` (None for the first shot, otherwise
    ``{"kind": "tail_frame", "from_shot_id": <previous shot_id>}``),
    and ``first_frame_ref`` (the caller's entry for that shot, or
    None). The result is JSON-serializable whenever the caller's
    first-frame refs are.

    Raises :class:`CapabilityError` on empty input, on a shot
    missing ``shot_id``, or on a duplicate ``shot_id``. Nothing is
    silently skipped or reordered.
    """
    if not isinstance(shots, list) or not shots:
        raise CapabilityError(
            "story.shot_chain: 'shots' must be a non-empty list"
        )
    seen: set[Any] = set()
    chain: list[dict[str, Any]] = []
    prev_shot_id: Any = None
    for shot in shots:
        if not isinstance(shot, dict):
            raise CapabilityError(
                "story.shot_chain: each shot must be an object with 'shot_id'"
            )
        shot_id = shot.get("shot_id")
        if shot_id is None or (isinstance(shot_id, str) and shot_id == ""):
            raise CapabilityError(
                "story.shot_chain: shot is missing 'shot_id'"
            )
        if shot_id in seen:
            raise CapabilityError(
                f"story.shot_chain: duplicate shot_id: {shot_id!r}"
            )
        seen.add(shot_id)
        if prev_shot_id is None:
            tail_frame_ref: dict[str, Any] | None = None
        else:
            tail_frame_ref = {
                "kind": "tail_frame",
                "from_shot_id": prev_shot_id,
            }
        chain.append(
            {
                "shot_id": shot_id,
                "prev_shot_id": prev_shot_id,
                "tail_frame_ref": tail_frame_ref,
                "first_frame_ref": _lookup_first_frame_ref(
                    first_frame_refs, shot_id
                ),
            }
        )
        prev_shot_id = shot_id
    return {"chain": chain}


def _as_link_list(chain: Any) -> list[Any]:
    """Accept either a link list or a build_chain result dict."""
    if isinstance(chain, dict) and "chain" in chain:
        return chain["chain"]
    if isinstance(chain, list):
        return chain
    raise CapabilityError(
        "story.shot_chain: 'chain' must be a list of links "
        "or a build_chain result dict"
    )


def validate_chain(chain: Any) -> list[dict[str, Any]]:
    """Validate a chain, returning one issue dict per problem found.

    Each issue is ``{shot_id, severity, code, message}``. Checks,
    in link order:

    * first link carrying a ``tail_frame_ref`` -> error
      (``first_shot_has_tail_frame``);
    * any later link missing its ``tail_frame_ref`` -> warning
      (``missing_tail_frame``);
    * a ``tail_frame_ref`` whose ``from_shot_id`` is not the
      immediately preceding link's ``shot_id`` -> error
      (``tail_frame_not_previous``).

    A clean chain returns an empty list. Duplicate ids and order
    drift cannot reach this function from :func:`build_chain`,
    which rejects them outright.
    """
    links = _as_link_list(chain)
    issues: list[dict[str, Any]] = []
    prev_shot_id: Any = None
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            # C-07: a non-dict link is an error, never silently skipped
            # (build_chain's "never silently skip" rule applies here too).
            issues.append(
                {
                    "shot_id": None,
                    "severity": "error",
                    "code": "non_dict_link",
                    "message": (
                        "Chain link must be an object with 'shot_id'; "
                        "a non-dict link cannot be validated as present."
                    ),
                }
            )
            continue
        shot_id = link.get("shot_id")
        tail = link.get("tail_frame_ref")
        if index == 0:
            if tail is not None:
                issues.append(
                    {
                        "shot_id": shot_id,
                        "severity": "error",
                        "code": "first_shot_has_tail_frame",
                        "message": (
                            "First shot must not carry a tail_frame_ref; "
                            "there is no preceding shot to link from."
                        ),
                    }
                )
        else:
            if tail is None:
                issues.append(
                    {
                        "shot_id": shot_id,
                        "severity": "warning",
                        "code": "missing_tail_frame",
                        "message": (
                            "Non-first shot is missing its tail_frame_ref; "
                            "continuity from the previous shot is not linked."
                        ),
                    }
                )
            elif not isinstance(tail, dict) or (
                tail.get("from_shot_id") != prev_shot_id
            ):
                issues.append(
                    {
                        "shot_id": shot_id,
                        "severity": "error",
                        "code": "tail_frame_not_previous",
                        "message": (
                            "tail_frame_ref must point at the immediately "
                            "preceding shot; it does not."
                        ),
                    }
                )
        prev_shot_id = shot_id
    return issues


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {"type": "array"},
        "first_frame_refs": {"anyOf": [{"type": "object"}, {"type": "array"}]},
    },
    "required": ["shots"],
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "shot_chain.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    # Report capability: aspect is declared but ignored (S-03); the
    # product is the chain JSON, not media.
    chain = build_chain(params["shots"], first_frame_refs=params.get("first_frame_refs"))
    issues = validate_chain(chain)
    payload = {
        **chain,
        "issues": issues,
        "passed": not any(i.get("severity") == "error" for i in issues),
    }
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_shot_chain_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.shot_chain",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "单集镜头链：按播出顺序给每镜挂上尾帧参照（下一镜从上一镜"
                "尾帧起）与调用方给定的首帧参照，绝不重排、绝不编造参照。"
                "报告类能力：产物为 chain JSON（aspects 仅声明，渲染忽略）。"
            ),
            line="shot_chain",
            has_media_output=False,
        )
    )
    return ["story.shot_chain"]


register_shot_chain_capabilities_once()
