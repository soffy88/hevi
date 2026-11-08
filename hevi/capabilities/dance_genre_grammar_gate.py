"""Dance genre-grammar gate (``qa.dance_genre_grammar_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): a dance film
first names its one main genre, because the body moves
differently in each. Twelve genres form the closed
vocabulary — classical Chinese, Han-Tang, Song style,
xianxia and Dunhuang fusion, J-pop idol, K-pop, hip-hop
and street, jazz funk, contemporary and lyrical, ballet,
cheer, and duo or group dance. Other genres may join
only as declared fusion, with a stated motive for why
they serve the main genre — never as an unruled pile-up,
and never by swapping one genre's moves straight into
another's. This gate judges the genre record only. It
dances nothing, renders nothing, and spends nothing:
``executed_here`` is always false.
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

GENRES: frozenset[str] = frozenset(
    {
        "classical_chinese",
        "han_tang",
        "song_style",
        "xianxia_dunhuang",
        "jpop_idol",
        "kpop",
        "hiphop_street",
        "jazz_funk",
        "contemporary_lyrical",
        "ballet",
        "cheer",
        "duo_group",
    }
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_genre_grammar(dance: Any) -> dict[str, Any]:
    """Validate the genre grammar of one dance MV.

    Verdicts are ``pass`` / ``fail`` only. The record fails
    when it names no main genre or one outside the closed
    vocabulary, when a fusion genre is unknown or repeats
    the main genre, when fusion arrives without a stated
    motive, or when any move belongs to a genre the record
    never declared.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(dance, dict):
        return fail("dance_not_object", "dance genre record must be a JSON object")
    primary = dance.get("primary_genre")
    if primary not in GENRES:
        return fail(
            "primary_genre_unknown",
            "dance must name one main genre from the closed vocabulary",
        )
    fusion = dance.get("fusion_genres", [])
    if not isinstance(fusion, list):
        return fail("fusion_not_list", "fusion genres must be a list, empty when none")
    for genre in fusion:
        if genre not in GENRES:
            return fail(
                "fusion_genre_unknown",
                f"fusion genre {genre!r} is outside the closed vocabulary",
            )
        if genre == primary:
            return fail(
                "fusion_repeats_primary",
                "a fusion genre must differ from the main genre",
            )
    if fusion:
        motive = dance.get("fusion_motive")
        if not isinstance(motive, str) or not motive.strip():
            return fail(
                "fusion_motive_missing",
                "fusion must state why it serves the main genre",
            )
    moves = dance.get("moves")
    if not isinstance(moves, list) or not moves:
        return fail("moves_missing", "dance must carry at least one move")
    allowed = {primary, *fusion}
    for position, move in enumerate(moves):
        if not isinstance(move, dict):
            return fail(
                "move_not_object",
                f"move {position} must be an object",
            )
        genre = move.get("genre")
        if genre not in GENRES:
            return fail(
                "move_genre_unknown",
                f"move {position} names unknown genre {genre!r}",
            )
        if genre not in allowed:
            return fail(
                "move_genre_undeclared",
                f"move {position} belongs to {genre}, which the record "
                "never declared as main or fusion genre",
            )
        if not isinstance(move.get("name"), str) or not move["name"].strip():
            return fail(
                "move_name_missing",
                f"move {position} must name the move",
            )
        if not isinstance(move.get("detail"), str) or not move["detail"].strip():
            return fail(
                "move_detail_missing",
                f"move {position} must describe how the body moves",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dance_genre_grammar(params.get("dance"))
    report_path = out_dir / "dance_genre_grammar_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_genre_grammar_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_genre_grammar_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "dance": {"type": "object"},
                },
                "required": ["dance"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance genre-grammar gate: one main genre from a "
                "closed twelve-genre vocabulary, declared fusion with "
                "a motive, and every move inside a declared genre."
            ),
        )
    )
    return ["qa.dance_genre_grammar_gate"]


__all__ = [
    "GENRES",
    "check_dance_genre_grammar",
    "register_dance_genre_grammar_gate_capabilities_once",
]
