"""Publish pack generator (``story.publish_pack_generator``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / B3 (stage 5, publish pack): a season's publish pack is
assembled from the season pack gate and caller-supplied per-episode
material -- cover descriptions, an end card with a next-episode
teaser, release copy, and an AI-generation label. Only the
*structure* is taken from the source method; no template text,
example name, or plot point from the source templates is copied:
every word of copy in the output is supplied verbatim by the
caller, and this module invents no plot, no hook, and no title.

Discipline kept, restated in hevi's own caliber:

1. The season pack must pass ``qa.season_pack_gate`` first. The
   pack's episode count, order, and hooks are the authority: an
   episode entry whose hook differs from the pack hook, or an
   episode count that differs from the pack, fails closed.
2. A cover is a *description only*. No cover image is generated
   here; the description names the caller-supplied subject and
   composition at two aspects (3:4 and 4:3). Text on the cover
   follows hevi's own thumbnail rule (at most 30 characters,
   see ``edit.publish_plan``); over-long cover text fails.
3. An end-card teaser may only quote the caller-supplied hook
   of the *next* episode in the pack. The final episode has no
   teaser; a teaser supplied for it fails rather than being
   published as if a next episode existed.
4. Release copy is assembled, never authored: exactly three
   caller-supplied hook titles, the caller-supplied synopsis
   (which must contain the pack hook, as the season gate
   requires), caller-supplied hashtags, and a caller-supplied
   pinned comment. Nothing is paraphrased.
5. Every pack carries an AI-generation label, marked
   human-review pending. Scale / platform compliance is
   caller-supplied or recorded ``not_checked``; it is never
   passed by default.

This module assembles text only. It posts nothing, holds no
account or key, calls no generator, and touches no budget.
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
from hevi.capabilities.season_pack_gate import check_season_pack

_Registered = False

_AI_DISCLOSURE = (
    "AI-generated content: the pictures and motion in this episode "
    "were produced with generative AI tools. Human review is pending."
)
_MAX_COVER_TEXT = 30


def _fail(message: str) -> CapabilityError:
    return CapabilityError(f"story.publish_pack_generator: {message}")


def _nonempty_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{what} must be a non-empty string")
    return value.strip()


def _str_list(value: Any, what: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise _fail(f"{what} must be a list of at least {minimum} item(s)")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _fail(f"{what} must contain only non-empty strings")
        out.append(item.strip())
    return out


def _pack_hooks(pack: dict[str, Any]) -> dict[int, str]:
    hooks: dict[int, str] = {}
    for episode in pack.get("episodes", []):
        if isinstance(episode, dict) and isinstance(episode.get("episode_no"), int):
            hook = episode.get("hook")
            if isinstance(hook, str):
                hooks[episode["episode_no"]] = hook.strip()
    return hooks


def build_publish_pack(
    season_pack: Any,
    episodes: Any,
    *,
    scale_declarations: Any = None,
) -> dict[str, Any]:
    """Assemble one publish pack from a season pack and episode material.

    Raises :class:`CapabilityError` for any mismatch with the season
    pack, any missing caller-supplied copy, or any invented teaser.
    """
    if not isinstance(season_pack, dict):
        raise _fail("season_pack must be a JSON object")
    gate = check_season_pack(season_pack)
    if gate["verdict"] != "pass":
        codes = ", ".join(sorted({i["code"] for i in gate["issues"]}))
        raise _fail(f"season pack fails qa.season_pack_gate ({codes}); no pack is built")
    hooks = _pack_hooks(season_pack)
    if not isinstance(episodes, list) or not episodes:
        raise _fail("episodes must be a non-empty list in play order")
    if len(episodes) != len(hooks):
        raise _fail(
            f"episode count {len(episodes)} does not match the season pack "
            f"episode count {len(hooks)}"
        )
    if scale_declarations is not None and not isinstance(scale_declarations, dict):
        raise _fail("scale_declarations must be a JSON object when supplied")

    synopses = season_pack.get("episode_synopses") or {}
    built: list[dict[str, Any]] = []
    for index, entry in enumerate(episodes):
        number = index + 1
        if not isinstance(entry, dict):
            raise _fail(f"episode {number} must be a JSON object")
        if entry.get("episode_no", number) != number:
            raise _fail(
                f"episode {number} must carry episode_no {number} in play order"
            )
        hook = _nonempty_str(entry.get("hook"), f"episode {number} hook")
        if hook != hooks.get(number):
            raise _fail(
                f"episode {number} hook does not match the season pack hook; "
                "the pack hook is authoritative"
            )
        synopsis = _nonempty_str(entry.get("synopsis"), f"episode {number} synopsis")
        if hook not in synopsis:
            raise _fail(
                f"episode {number} synopsis does not contain the pack hook; "
                "hook and synopsis must agree"
            )
        if isinstance(synopses, dict) and str(number) in synopses:
            declared = synopses[str(number)]
            if isinstance(declared, str) and declared.strip() != synopsis:
                raise _fail(
                    f"episode {number} synopsis does not match the season pack "
                    "episode_synopses entry"
                )
        titles = _str_list(entry.get("hook_titles"), f"episode {number} hook_titles")
        if len(titles) != 3:
            raise _fail(
                f"episode {number} must supply exactly 3 hook_titles, got {len(titles)}"
            )
        hashtags = _str_list(entry.get("hashtags"), f"episode {number} hashtags")
        pinned = _nonempty_str(
            entry.get("pinned_comment"), f"episode {number} pinned_comment"
        )
        cover = entry.get("cover")
        if not isinstance(cover, dict):
            raise _fail(f"episode {number} cover must be a JSON object")
        subject = _nonempty_str(cover.get("subject"), f"episode {number} cover.subject")
        composition = _nonempty_str(
            cover.get("composition"), f"episode {number} cover.composition"
        )
        cover_text = cover.get("text_on_cover", "")
        if not isinstance(cover_text, str):
            raise _fail(f"episode {number} cover.text_on_cover must be a string")
        if len(cover_text) > _MAX_COVER_TEXT:
            raise _fail(
                f"episode {number} cover text is {len(cover_text)} characters; "
                f"at most {_MAX_COVER_TEXT} are allowed"
            )
        next_hook = entry.get("next_hook")
        is_last = number == len(episodes)
        if is_last:
            if isinstance(next_hook, str) and next_hook.strip():
                raise _fail(
                    f"episode {number} is the last episode in the pack; "
                    "a next-episode teaser must not be supplied for it"
                )
            end_card: dict[str, Any] = {
                "next_episode_no": None,
                "teaser_text": None,
                "status": "no_next_episode",
            }
        else:
            teaser = _nonempty_str(
                next_hook, f"episode {number} next_hook"
            )
            if teaser != hooks.get(number + 1):
                raise _fail(
                    f"episode {number} next_hook does not match the season "
                    f"pack hook of episode {number + 1}; a teaser may only "
                    "quote the next episode's pack hook"
                )
            end_card = {
                "next_episode_no": number + 1,
                "teaser_text": teaser,
                "status": "teaser_from_caller_hook",
            }
        built.append(
            {
                "episode_no": number,
                "hook": hook,
                "cover": {
                    "aspects": {
                        "3:4": {
                            "subject": subject,
                            "composition": composition,
                            "text_on_cover": cover_text,
                        },
                        "4:3": {
                            "subject": subject,
                            "composition": composition,
                            "text_on_cover": cover_text,
                        },
                    },
                    "image_status": (
                        "description_only: no cover image was generated "
                        "by this capability"
                    ),
                },
                "end_card": end_card,
                "copy": {
                    "hook_titles": titles,
                    "synopsis": synopsis,
                    "hashtags": hashtags,
                    "pinned_comment": pinned,
                },
                "ai_label": {
                    "ai_generated": True,
                    "disclosure": _AI_DISCLOSURE,
                    "human_review": "pending",
                    "scale_declarations": (
                        scale_declarations
                        if scale_declarations is not None
                        else "not_checked"
                    ),
                    "platform_rules": (
                        "not_checked: confirm against the target "
                        "platform's current rules before publishing"
                    ),
                },
            }
        )
    return {
        "season_no": season_pack.get("season_no"),
        "episode_count": len(built),
        "episodes": built,
        "status": "draft_not_published",
        "note": (
            "This capability assembles text only and never posts; "
            "publishing needs a separate approval, credentials, and "
            "human review of the AI label."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    pack = build_publish_pack(
        params.get("season_pack"),
        params.get("episodes"),
        scale_declarations=params.get("scale_declarations"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "publish_pack.json"
    report_path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "season_no": pack["season_no"],
            "episode_count": pack["episode_count"],
            "status": pack["status"],
        },
    )


def register_publish_pack_generator_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.publish_pack_generator",
            kind="line",
            aspects=["9:16", "16:9"],
            params_schema={
                "type": "object",
                "properties": {
                    "season_pack": {"type": "object"},
                    "episodes": {"type": "array"},
                    "scale_declarations": {"type": "object"},
                },
                "required": ["season_pack", "episodes"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Publish pack generator (ai-manju B3, clean-room): "
                "assembles cover descriptions, end-card teasers, "
                "release copy, and an AI-generation label from a "
                "season pack that passes qa.season_pack_gate and "
                "caller-supplied episode material. Copy is never "
                "authored here; teasers quote only the next "
                "episode's pack hook. Text only; never posts. See "
                "AI_MANJU_ATTRIBUTION.md."
            ),
            line="story",
        )
    )
    return ["story.publish_pack_generator"]


register_publish_pack_generator_capabilities_once()
