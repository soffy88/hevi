"""Author HEVI's deterministic 33-dimension audit gold corpus.

This script is the *source of truth* for the fixtures committed under
``tests/fixtures/creative_audit_gold``.  Every fixture is authored here as a
concrete narrative situation (artifact text, structured draft claims,
reconstructed canon state) together with the findings a correct audit must
produce.  Nothing is copied from an upstream repository.

Run::

    python scripts/qualification/build_audit_gold.py

The generator is deterministic; re-running it reproduces the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
OUTPUT = ROOT / "tests/fixtures/creative_audit_gold"

BASE_TEXT = "Mara crossed the quiet yard and reached the gate."
BASE_SCENE: dict[str, Any] = {
    "sequence": 1,
    "purpose": "establish the crossing",
    "objective": "reach the gate",
    "beat_kind": "turn",
}

DIMENSIONS: tuple[str, ...] = (
    "CHARACTER_CONTINUITY",
    "CHARACTER_VOICE",
    "WORLD_CONTINUITY",
    "TIMELINE_CONTINUITY",
    "LOCATION_CONTINUITY",
    "OBJECT_CONTINUITY",
    "RESOURCE_CONTINUITY",
    "RELATIONSHIP_CONTINUITY",
    "INFORMATION_CONTINUITY",
    "EMOTIONAL_CONTINUITY",
    "PHYSICAL_STATE_CONTINUITY",
    "MOTIVATION_CONTINUITY",
    "FACT_CONSISTENCY",
    "HOOK_CONTINUITY",
    "FORESHADOWING",
    "PAYOFF",
    "ARC_ALIGNMENT",
    "SCENE_PURPOSE",
    "PACING",
    "REPETITION",
    "DIALOGUE_QUALITY",
    "PROSE_CLARITY",
    "STYLE_ALIGNMENT",
    "GENRE_ALIGNMENT",
    "FATIGUE_WORDS",
    "LENGTH_GOVERNANCE",
    "STRUCTURE",
    "POINT_OF_VIEW",
    "TONE",
    "VISUAL_FILMABILITY",
    "SHOT_FEASIBILITY",
    "SAFETY",
    "AUTHOR_INTENT_ALIGNMENT",
)


def _claim(
    dimension: str,
    subject: str,
    predicate: str,
    value: str,
    location: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dimension": dimension,
        "subject": subject,
        "predicate": predicate,
        "value": value,
    }
    if location is not None:
        payload["location"] = location
    if ref is not None:
        payload["entity_ref"] = ref
    return payload


def _canon(
    dimension: str,
    subject: str,
    predicate: str,
    value: str,
    ref: str | None = None,
) -> dict[str, Any]:
    return _claim(dimension, subject, predicate, value, None, ref)


def _scene(
    sequence: int,
    *,
    purpose: str = "advance the crossing",
    objective: str = "reach the gate",
    beat_kind: str | None = "turn",
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "purpose": purpose,
        "objective": objective,
        "beat_kind": beat_kind,
    }


def _context(
    *,
    text: str = BASE_TEXT,
    claims: list[dict[str, Any]] | None = None,
    scenes: list[dict[str, Any]] | None = None,
    canon: list[dict[str, Any]] | None = None,
    entities: list[str] | None = None,
    style: dict[str, Any] | None = None,
    genre: dict[str, Any] | None = None,
    author_intent: dict[str, Any] | None = None,
    length_target: dict[str, Any] | None = None,
    shot_constraints: list[str] | None = None,
    hook_deadlines: list[list[Any]] | None = None,
    payoff_setup_refs: list[list[str]] | None = None,
    current_chapter: int = 1,
) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "text": text,
        "claims": claims or [],
        "scenes": scenes if scenes is not None else [dict(BASE_SCENE)],
    }
    artifact.update(
        {
            key: value
            for key, value in (
                ("style", style),
                ("genre", genre),
                ("author_intent", author_intent),
                ("length_target", length_target),
            )
            if value is not None
        }
    )
    if shot_constraints:
        artifact["shot_constraints"] = shot_constraints
    canon_state: dict[str, Any] = {
        "canon_facts": canon or [],
        "known_entities": entities or [],
        "hook_deadlines": hook_deadlines or [],
        "payoff_setup_refs": payoff_setup_refs or [],
        "current_chapter": current_chapter,
    }
    return {"input_artifact": artifact, "canon_state": canon_state}


def _fixture(
    fixture_id: str,
    dimension: str,
    case_type: str,
    context: dict[str, Any],
    *,
    expected: list[dict[str, str]] | None = None,
    severities: list[str] | None = None,
    locations: list[str | None] | None = None,
    refs: list[list[str]] | None = None,
    must_not: list[str] | None = None,
    rationale: str,
) -> dict[str, Any]:
    expected = expected or []
    return {
        "fixture_id": fixture_id,
        "dimension": dimension,
        "case_type": case_type,
        "input_artifact": context["input_artifact"],
        "canon_state": context["canon_state"],
        "expected_findings": expected,
        "expected_severity": severities or [],
        "expected_location": locations or [],
        "expected_canonical_refs": refs or [],
        "must_not_find": must_not or [],
        "rationale": rationale,
    }


def _positive(
    dimension: str,
    index: int,
    context: dict[str, Any],
    expectations: list[tuple[str, str, str | None, list[str]]],
    rationale: str,
) -> dict[str, Any]:
    return _fixture(
        f"{dimension}-POS-{index:02d}",
        dimension,
        "POSITIVE",
        context,
        expected=[{"dimension": dimension, "code": code} for code, _, _, _ in expectations],
        severities=[severity for _, severity, _, _ in expectations],
        locations=[location for _, _, location, _ in expectations],
        refs=[refs for _, _, _, refs in expectations],
        must_not=[],
        rationale=rationale,
    )


def _negative(dimension: str, index: int, context: dict[str, Any], rationale: str) -> dict[str, Any]:
    return _fixture(
        f"{dimension}-NEG-{index:02d}",
        dimension,
        "NEGATIVE",
        context,
        must_not=[dimension],
        rationale=rationale,
    )


def _continuity_pair(
    dimension: str,
    *,
    subject: str,
    predicate: str,
    canon_value: str,
    draft_value: str,
    prefix: str,
    ref: str,
    severity: str = "ERROR",
) -> tuple[dict[str, Any], dict[str, Any]]:
    positive = _context(
        claims=[_claim(dimension, subject, predicate, draft_value, "sentence:1", ref)],
        canon=[_canon(dimension, subject, predicate, canon_value, ref)],
    )
    consistent = _context(
        claims=[_claim(dimension, subject, predicate, canon_value, "sentence:1", ref)],
        canon=[_canon(dimension, subject, predicate, canon_value, ref)],
    )
    return positive, consistent


def build() -> dict[str, list[dict[str, Any]]]:
    corpus: dict[str, list[dict[str, Any]]] = {}

    def emit(dimension: str, fixtures: list[dict[str, Any]]) -> None:
        corpus[dimension] = fixtures

    # --- hard continuity dimensions -------------------------------------
    positive, consistent = _continuity_pair(
        "CHARACTER_CONTINUITY",
        subject="Mara",
        predicate="eye_color",
        canon_value="green",
        draft_value="blue",
        prefix="CC",
        ref="character:mara",
    )
    emit(
        "CHARACTER_CONTINUITY",
        [
            _positive(
                "CHARACTER_CONTINUITY",
                1,
                positive,
                [("CC_CONFLICT", "ERROR", "sentence:1", ["character:mara"])],
                "Draft changes Mara's canon eye colour.",
            ),
            _positive(
                "CHARACTER_CONTINUITY",
                2,
                _context(
                    text=BASE_TEXT,
                    claims=[
                        _claim(
                            "CHARACTER_CONTINUITY",
                            "Ghost",
                            "presence",
                            "here",
                            "sentence:1",
                            "character:ghost",
                        )
                    ],
                    entities=["character:mara"],
                ),
                [("CC_UNKNOWN_ENTITY", "ERROR", "sentence:1", ["character:ghost"])],
                "Draft introduces a character absent from canon.",
            ),
            _negative(
                "CHARACTER_CONTINUITY",
                1,
                _context(),
                "No draft claim is made, so nothing can conflict with canon.",
            ),
            _negative(
                "CHARACTER_CONTINUITY",
                2,
                consistent,
                "Draft repeats the canon value, so there is no conflict.",
            ),
        ],
    )

    voice_consistent = _context(
        claims=[
            _claim(
                "CHARACTER_VOICE",
                "Mara",
                "line",
                "I will not go back",
                "sentence:2",
                "character:mara",
            )
        ],
        canon=[_canon("CHARACTER_VOICE", "Mara", "forbidden", "ain't", "character:mara")],
    )
    emit(
        "CHARACTER_VOICE",
        [
            _positive(
                "CHARACTER_VOICE",
                1,
                _context(
                    claims=[
                        _claim(
                            "CHARACTER_VOICE",
                            "Mara",
                            "line",
                            "I ain't going back",
                            "sentence:2",
                            "character:mara",
                        )
                    ],
                    canon=[
                        _canon("CHARACTER_VOICE", "Mara", "forbidden", "ain't", "character:mara")
                    ],
                ),
                [("CV_FORBIDDEN_PATTERN", "WARN", "sentence:2", ["character:mara"])],
                "Mara's line uses a pattern forbidden by her voice contract.",
            ),
            _negative("CHARACTER_VOICE", 1, _context(), "No dialogue claim is present."),
            _negative(
                "CHARACTER_VOICE",
                2,
                voice_consistent,
                "The voice fact is registered but no line violates it.",
            ),
        ],
    )

    positive, consistent = _continuity_pair(
        "WORLD_CONTINUITY",
        subject="magic",
        predicate="cost",
        canon_value="blood",
        draft_value="nothing",
        prefix="WC",
        ref="world:magic",
    )
    emit(
        "WORLD_CONTINUITY",
        [
            _positive(
                "WORLD_CONTINUITY",
                1,
                positive,
                [("WC_CONFLICT", "ERROR", "sentence:1", ["world:magic"])],
                "Draft breaks the canon rule that magic costs blood.",
            ),
            _negative("WORLD_CONTINUITY", 1, _context(), "No world claim is present."),
            _negative(
                "WORLD_CONTINUITY",
                2,
                consistent,
                "Draft honours the world rule.",
            ),
        ],
    )

    emit(
        "TIMELINE_CONTINUITY",
        [
            _positive(
                "TIMELINE_CONTINUITY",
                1,
                _context(
                    claims=[
                        _claim(
                            "TIMELINE_CONTINUITY", "battle", "order", "2", "sentence:1", "event:battle"
                        )
                    ],
                    canon=[_canon("TIMELINE_CONTINUITY", "battle", "order", "5", "event:battle")],
                ),
                [
                    ("TC_CONFLICT", "ERROR", "sentence:1", ["event:battle"]),
                    ("TC_ORDER_VIOLATION", "ERROR", "sentence:1", ["event:battle"]),
                ],
                "Draft places the battle before its canon prerequisite.",
            ),
            _positive(
                "TIMELINE_CONTINUITY",
                2,
                _context(
                    claims=[
                        _claim(
                            "TIMELINE_CONTINUITY", "battle", "order", "9", "sentence:1", "event:battle"
                        )
                    ],
                    canon=[_canon("TIMELINE_CONTINUITY", "battle", "order", "5", "event:battle")],
                ),
                [("TC_CONFLICT", "ERROR", "sentence:1", ["event:battle"])],
                "Draft moves the battle to a different but non-violating order.",
            ),
            _negative("TIMELINE_CONTINUITY", 1, _context(), "No timeline claim is present."),
            _negative(
                "TIMELINE_CONTINUITY",
                2,
                _context(
                    claims=[
                        _claim(
                            "TIMELINE_CONTINUITY", "battle", "order", "5", "sentence:1", "event:battle"
                        )
                    ],
                    canon=[_canon("TIMELINE_CONTINUITY", "battle", "order", "5", "event:battle")],
                ),
                "Draft keeps the canon event order.",
            ),
        ],
    )

    emit(
        "LOCATION_CONTINUITY",
        [
            _positive(
                "LOCATION_CONTINUITY",
                1,
                _context(
                    claims=[_claim("LOCATION_CONTINUITY", "gate", "state", "open", "sentence:1", "location:gate")],
                    canon=[_canon("LOCATION_CONTINUITY", "gate", "state", "closed", "location:gate")],
                ),
                [("LC_CONFLICT", "ERROR", "sentence:1", ["location:gate"])],
                "Draft opens a gate that canon records as closed.",
            ),
            _positive(
                "LOCATION_CONTINUITY",
                2,
                _context(
                    claims=[
                        _claim("LOCATION_CONTINUITY", "Mara", "location", "harbour"),
                        _claim("LOCATION_CONTINUITY", "Mara", "location", "tower"),
                    ],
                ),
                [("LC_MULTIPLE_LOCATIONS", "ERROR", None, ["character:Mara"])],
                "One character occupies two locations in the same scene.",
            ),
            _negative("LOCATION_CONTINUITY", 1, _context(), "No location claim is present."),
            _negative(
                "LOCATION_CONTINUITY",
                2,
                _context(
                    claims=[_claim("LOCATION_CONTINUITY", "gate", "state", "closed", "sentence:1", "location:gate")],
                    canon=[_canon("LOCATION_CONTINUITY", "gate", "state", "closed", "location:gate")],
                ),
                "Draft and canon agree on the location state.",
            ),
        ],
    )

    positive, consistent = _continuity_pair(
        "OBJECT_CONTINUITY",
        subject="key",
        predicate="state",
        canon_value="destroyed",
        draft_value="intact",
        prefix="OC",
        ref="object:key",
    )
    emit(
        "OBJECT_CONTINUITY",
        [
            _positive(
                "OBJECT_CONTINUITY",
                1,
                positive,
                [("OC_CONFLICT", "ERROR", "sentence:1", ["object:key"])],
                "Draft uses an object canon records as destroyed.",
            ),
            _negative("OBJECT_CONTINUITY", 1, _context(), "No object claim is present."),
            _negative("OBJECT_CONTINUITY", 2, consistent, "Object state matches canon."),
        ],
    )

    positive, consistent = _continuity_pair(
        "RESOURCE_CONTINUITY",
        subject="potions",
        predicate="quantity",
        canon_value="2",
        draft_value="4",
        prefix="RSC",
        ref="resource:potions",
    )
    emit(
        "RESOURCE_CONTINUITY",
        [
            _positive(
                "RESOURCE_CONTINUITY",
                1,
                positive,
                [("RSC_CONFLICT", "ERROR", "sentence:1", ["resource:potions"])],
                "Draft spends more of a resource than canon holds.",
            ),
            _negative("RESOURCE_CONTINUITY", 1, _context(), "No resource claim is present."),
            _negative("RESOURCE_CONTINUITY", 2, consistent, "Resource quantity matches canon."),
        ],
    )

    positive, consistent = _continuity_pair(
        "RELATIONSHIP_CONTINUITY",
        subject="Mara-Ash",
        predicate="type",
        canon_value="ally",
        draft_value="enemy",
        prefix="REL",
        ref="relationship:mara-ash",
    )
    emit(
        "RELATIONSHIP_CONTINUITY",
        [
            _positive(
                "RELATIONSHIP_CONTINUITY",
                1,
                positive,
                [("REL_CONFLICT", "ERROR", "sentence:1", ["relationship:mara-ash"])],
                "Draft reverses a canon relationship.",
            ),
            _negative("RELATIONSHIP_CONTINUITY", 1, _context(), "No relationship claim is present."),
            _negative(
                "RELATIONSHIP_CONTINUITY", 2, consistent, "Relationship matches canon."
            ),
        ],
    )

    positive, consistent = _continuity_pair(
        "INFORMATION_CONTINUITY",
        subject="Mara",
        predicate="knows_secret",
        canon_value="unknown",
        draft_value="known",
        prefix="IC",
        ref="information:secret",
    )
    emit(
        "INFORMATION_CONTINUITY",
        [
            _positive(
                "INFORMATION_CONTINUITY",
                1,
                positive,
                [("IC_CONFLICT", "ERROR", "sentence:1", ["information:secret"])],
                "Draft has a character acting on knowledge canon says is unknown.",
            ),
            _negative("INFORMATION_CONTINUITY", 1, _context(), "No information claim is present."),
            _negative(
                "INFORMATION_CONTINUITY", 2, consistent, "Information state matches canon."
            ),
        ],
    )

    positive, consistent = _continuity_pair(
        "EMOTIONAL_CONTINUITY",
        subject="Mara",
        predicate="emotion",
        canon_value="calm",
        draft_value="furious",
        prefix="EC",
        ref="character:mara",
        severity="WARN",
    )
    emit(
        "EMOTIONAL_CONTINUITY",
        [
            _positive(
                "EMOTIONAL_CONTINUITY",
                1,
                positive,
                [("EC_UNMOTIVATED_SHIFT", "WARN", "sentence:1", ["character:mara"])],
                "Draft shifts emotion without a bridging beat.",
            ),
            _negative("EMOTIONAL_CONTINUITY", 1, _context(), "No emotion claim is present."),
            _negative("EMOTIONAL_CONTINUITY", 2, consistent, "Emotion matches canon."),
        ],
    )

    positive, consistent = _continuity_pair(
        "PHYSICAL_STATE_CONTINUITY",
        subject="Mara",
        predicate="arm",
        canon_value="broken",
        draft_value="fine",
        prefix="PSC",
        ref="character:mara",
    )
    emit(
        "PHYSICAL_STATE_CONTINUITY",
        [
            _positive(
                "PHYSICAL_STATE_CONTINUITY",
                1,
                positive,
                [("PSC_CONFLICT", "ERROR", "sentence:1", ["character:mara"])],
                "Draft has an injured character acting uninjured.",
            ),
            _negative("PHYSICAL_STATE_CONTINUITY", 1, _context(), "No physical claim is present."),
            _negative(
                "PHYSICAL_STATE_CONTINUITY", 2, consistent, "Physical state matches canon."
            ),
        ],
    )

    positive, consistent = _continuity_pair(
        "MOTIVATION_CONTINUITY",
        subject="Mara",
        predicate="motivation",
        canon_value="protect sister",
        draft_value="abandon sister",
        prefix="MC",
        ref="character:mara",
        severity="WARN",
    )
    emit(
        "MOTIVATION_CONTINUITY",
        [
            _positive(
                "MOTIVATION_CONTINUITY",
                1,
                positive,
                [("MC_CONFLICT", "WARN", "sentence:1", ["character:mara"])],
                "Draft action contradicts the canon motivation.",
            ),
            _negative("MOTIVATION_CONTINUITY", 1, _context(), "No motivation claim is present."),
            _negative("MOTIVATION_CONTINUITY", 2, consistent, "Motivation matches canon."),
        ],
    )

    positive, consistent = _continuity_pair(
        "FACT_CONSISTENCY",
        subject="moon",
        predicate="color",
        canon_value="silver",
        draft_value="red",
        prefix="FC",
        ref="fact:moon",
    )
    emit(
        "FACT_CONSISTENCY",
        [
            _positive(
                "FACT_CONSISTENCY",
                1,
                positive,
                [("FC_CONFLICT", "ERROR", "sentence:1", ["fact:moon"])],
                "Draft states a fact that contradicts canon.",
            ),
            _negative("FACT_CONSISTENCY", 1, _context(), "No factual claim is present."),
            _negative("FACT_CONSISTENCY", 2, consistent, "Fact matches canon."),
        ],
    )

    emit(
        "HOOK_CONTINUITY",
        [
            _positive(
                "HOOK_CONTINUITY",
                1,
                _context(hook_deadlines=[["hook:letter", 2]], current_chapter=5),
                [("HC_STALE_HOOK", "ERROR", None, ["hook:letter"])],
                "An open hook passed its deadline without resolution.",
            ),
            _positive(
                "HOOK_CONTINUITY",
                2,
                _context(
                    claims=[
                        _claim(
                            "HOOK_CONTINUITY",
                            "hook:letter",
                            "status",
                            "resolved",
                            None,
                            "hook:letter",
                        )
                    ],
                    canon=[
                        _canon(
                            "HOOK_CONTINUITY", "hook:letter", "status", "open", "hook:letter"
                        )
                    ],
                ),
                [("HC_CONFLICT", "ERROR", None, ["hook:letter"])],
                "Draft resolves a hook in a way that contradicts canon.",
            ),
            _negative("HOOK_CONTINUITY", 1, _context(), "No hook is tracked."),
            _negative(
                "HOOK_CONTINUITY",
                2,
                _context(hook_deadlines=[["hook:letter", 9]], current_chapter=3),
                "The hook is still within its deadline.",
            ),
        ],
    )

    # --- craft / quality dimensions -------------------------------------
    emit(
        "FORESHADOWING",
        [
            _positive(
                "FORESHADOWING",
                1,
                _context(
                    claims=[
                        _claim(
                            "FORESHADOWING",
                            "gun",
                            "setup",
                            "a gun on the wall",
                            "sentence:2",
                            "foreshadow:gun",
                        )
                    ]
                ),
                [("FS_NO_PAYOFF", "WARN", "sentence:2", ["foreshadow:gun"])],
                "A foreshadow has no registered payoff.",
            ),
            _negative("FORESHADOWING", 1, _context(), "No foreshadow is present."),
            _negative(
                "FORESHADOWING",
                2,
                _context(
                    claims=[
                        _claim(
                            "FORESHADOWING",
                            "gun",
                            "setup",
                            "a gun on the wall",
                            "sentence:2",
                            "foreshadow:gun",
                        ),
                        _claim(
                            "PAYOFF",
                            "gun",
                            "payoff",
                            "the gun fires",
                            "sentence:3",
                            "payoff:gun",
                        ),
                    ],
                    payoff_setup_refs=[["gun", "foreshadow:gun"]],
                ),
                "The setup has a matching registered payoff.",
            ),
        ],
    )

    emit(
        "PAYOFF",
        [
            _positive(
                "PAYOFF",
                1,
                _context(
                    claims=[
                        _claim("PAYOFF", "gunshot", "payoff", "the gun fires", "sentence:2", "payoff:gunshot")
                    ]
                ),
                [("PO_NO_SETUP", "WARN", "sentence:2", ["payoff:gunshot"])],
                "A payoff has no matching setup.",
            ),
            _negative("PAYOFF", 1, _context(), "No payoff is present."),
            _negative(
                "PAYOFF",
                2,
                _context(
                    claims=[
                        _claim("PAYOFF", "gunshot", "payoff", "the gun fires", "sentence:2", "payoff:gunshot")
                    ],
                    payoff_setup_refs=[["gunshot", "foreshadow:gun"]],
                ),
                "The payoff has a registered setup.",
            ),
        ],
    )

    emit(
        "ARC_ALIGNMENT",
        [
            _positive(
                "ARC_ALIGNMENT",
                1,
                _context(
                    scenes=[_scene(1, purpose="errand", objective="buy bread")],
                    canon=[_canon("ARC_ALIGNMENT", "arc:revenge", "goal", "avenge father", "arc:revenge")],
                ),
                [("AA_BEAT_OFF_ARC", "WARN", "scene:1", ["arc:revenge"])],
                "A scene objective does not advance any registered arc goal.",
            ),
            _negative("ARC_ALIGNMENT", 1, _context(), "No arc goal is registered."),
            _negative(
                "ARC_ALIGNMENT",
                2,
                _context(
                    scenes=[_scene(1, purpose="revenge beat", objective="avenge father")],
                    canon=[_canon("ARC_ALIGNMENT", "arc:revenge", "goal", "avenge father", "arc:revenge")],
                ),
                "The scene objective advances the registered arc.",
            ),
        ],
    )

    emit(
        "SCENE_PURPOSE",
        [
            _positive(
                "SCENE_PURPOSE",
                1,
                _context(scenes=[_scene(1, purpose="", objective="")]),
                [("SP_MISSING_PURPOSE", "ERROR", "scene:1", [])],
                "A scene lacks purpose and objective.",
            ),
            _negative("SCENE_PURPOSE", 1, _context(), "The base scene is complete."),
            _negative(
                "SCENE_PURPOSE",
                2,
                _context(scenes=[_scene(1), _scene(2, purpose="complicate", objective="lose the key")]),
                "Both scenes declare purpose and objective.",
            ),
        ],
    )

    emit(
        "PACING",
        [
            _positive(
                "PACING",
                1,
                _context(
                    scenes=[
                        _scene(1, purpose="talk", objective="reach the gate", beat_kind="dialogue"),
                        _scene(2, purpose="reflect", objective="reach the gate", beat_kind="reflection"),
                        _scene(3, purpose="turn", objective="reach the gate", beat_kind="turn"),
                    ],
                    genre={"name": "action", "min_action_ratio": 0.5},
                ),
                [("PA_PROFILE_DEVIATION", "WARN", "scene:all", ["genre:action"])],
                "Action density is below the genre pacing floor.",
            ),
            _negative("PACING", 1, _context(), "No genre pacing profile is configured."),
            _negative(
                "PACING",
                2,
                _context(
                    scenes=[
                        _scene(1, beat_kind="action"),
                        _scene(2, beat_kind="action"),
                        _scene(3, beat_kind="turn"),
                    ],
                    genre={"name": "action", "min_action_ratio": 0.5},
                ),
                "Action density meets the genre floor.",
            ),
        ],
    )

    emit(
        "REPETITION",
        [
            _positive(
                "REPETITION",
                1,
                _context(text="It was very very very cold."),
                [("RP_REPEATED_PHRASE", "WARN", "sentence:1", [])],
                "A word repeats three times in a row.",
            ),
            _negative("REPETITION", 1, _context(), "The base text has no repeated phrase."),
            _negative(
                "REPETITION",
                2,
                _context(text="Mara crossed the yard. The gate stood open. Wind moved the grass."),
                "Three varied sentences with distinct openings.",
            ),
        ],
    )

    emit(
        "DIALOGUE_QUALITY",
        [
            _positive(
                "DIALOGUE_QUALITY",
                1,
                _context(text='Mara said, "As you know, the gate opens at dawn."'),
                [("DQ_EXPOSITION", "WARN", "sentence:1", [])],
                "Dialogue states plot information with an exposition marker.",
            ),
            _negative("DIALOGUE_QUALITY", 1, _context(), "The base text contains no dialogue."),
            _negative(
                "DIALOGUE_QUALITY",
                2,
                _context(text='Mara said, "The gate is open." Then she ran.'),
                "Dialogue is short and does not expose plot.",
            ),
        ],
    )

    emit(
        "PROSE_CLARITY",
        [
            _positive(
                "PROSE_CLARITY",
                1,
                _context(text=""),
                [("PC_EMPTY_TEXT", "ERROR", "text:empty", [])],
                "An empty draft cannot be reviewed.",
            ),
            _negative("PROSE_CLARITY", 1, _context(), "The base text is short and clear."),
            _negative(
                "PROSE_CLARITY",
                2,
                _context(text="The gate opened. Mara stepped through. Ash waited beyond."),
                "Short, unambiguous sentences.",
            ),
        ],
    )

    emit(
        "STYLE_ALIGNMENT",
        [
            _positive(
                "STYLE_ALIGNMENT",
                1,
                _context(
                    text="The wind moved across the empty yard while the tall gate stood open before her.",
                    style={"sentence_length": 4.0},
                ),
                [("SA_SENTENCE_LENGTH_DRIFT", "WARN", "text:all", [])],
                "Sentence length drifts far above the style profile.",
            ),
            _negative("STYLE_ALIGNMENT", 1, _context(), "No style profile is configured."),
            _negative(
                "STYLE_ALIGNMENT",
                2,
                _context(style={"sentence_length": 9.0}),
                "Observed sentence length matches the profile.",
            ),
        ],
    )

    emit(
        "GENRE_ALIGNMENT",
        [
            _positive(
                "GENRE_ALIGNMENT",
                1,
                _context(
                    text="A spell lit the gate.",
                    genre={
                        "name": "mystery",
                        "required_patterns": ["clue"],
                        "forbidden_patterns": ["spell"],
                    },
                ),
                [
                    ("GA_FORBIDDEN_PATTERN", "ERROR", "sentence:1", ["genre:mystery"]),
                    ("GA_REQUIRED_RULE_UNMET", "WARN", "text:all", ["genre:mystery"]),
                ],
                "The draft uses a forbidden pattern and omits a required genre element.",
            ),
            _negative("GENRE_ALIGNMENT", 1, _context(), "No genre profile is configured."),
            _negative(
                "GENRE_ALIGNMENT",
                2,
                _context(
                    genre={"name": "mystery", "required_patterns": ["gate"]},
                ),
                "The required genre element is present.",
            ),
        ],
    )

    emit(
        "FATIGUE_WORDS",
        [
            _positive(
                "FATIGUE_WORDS",
                1,
                _context(
                    text=(
                        "The gate moved suddenly. It stopped suddenly. "
                        "Then the wind fell suddenly. All went still suddenly."
                    ),
                    genre={"name": "thriller", "fatigue_lexicon": ["suddenly"]},
                ),
                [("FW_OVERUSED", "WARN", "text:all", ["genre:thriller"])],
                "A fatigue word is used more than three times.",
            ),
            _negative("FATIGUE_WORDS", 1, _context(), "No fatigue lexicon is configured."),
            _negative(
                "FATIGUE_WORDS",
                2,
                _context(genre={"name": "thriller", "fatigue_lexicon": ["suddenly"]}),
                "The fatigue word never appears.",
            ),
        ],
    )

    emit(
        "LENGTH_GOVERNANCE",
        [
            _positive(
                "LENGTH_GOVERNANCE",
                1,
                _context(length_target={"min_words": 100}),
                [("LG_BELOW_TARGET", "WARN", "text:all", [])],
                "Draft falls below the configured word floor.",
            ),
            _negative("LENGTH_GOVERNANCE", 1, _context(), "No length target is configured."),
            _negative(
                "LENGTH_GOVERNANCE",
                2,
                _context(length_target={"min_words": 1, "max_words": 50}),
                "Draft is within the configured length band.",
            ),
        ],
    )

    emit(
        "STRUCTURE",
        [
            _positive(
                "STRUCTURE",
                1,
                _context(scenes=[_scene(1), _scene(3)]),
                [("ST_SCENE_ORDER", "ERROR", "scene:all", [])],
                "Scene sequence has a gap.",
            ),
            _negative("STRUCTURE", 1, _context(), "The base scene sequence is contiguous."),
            _negative(
                "STRUCTURE",
                2,
                _context(scenes=[_scene(1), _scene(2, purpose="second", objective="hold the gate")]),
                "Two contiguous scenes with a turn.",
            ),
        ],
    )

    emit(
        "POINT_OF_VIEW",
        [
            _positive(
                "POINT_OF_VIEW",
                1,
                _context(text="I ran toward the gate. He followed."),
                [("POV_HEAD_HOPPING", "WARN", "text:all", [])],
                "First-person and third-person markers are mixed.",
            ),
            _negative("POINT_OF_VIEW", 1, _context(), "No point-of-view markers are mixed."),
            _negative(
                "POINT_OF_VIEW",
                2,
                _context(text="Mara ran toward the gate. Ash followed her.", style={"pov": "third-limited"}),
                "Narration holds a single third-person point of view.",
            ),
        ],
    )

    emit(
        "TONE",
        [
            _positive(
                "TONE",
                1,
                _context(style={"tone": ["elegiac"]}),
                [("TN_TONE_DRIFT", "WARN", "text:all", [])],
                "None of the declared tones appear in the prose.",
            ),
            _negative("TONE", 1, _context(), "No tone profile is configured."),
            _negative(
                "TONE",
                2,
                _context(style={"tone": ["quiet"]}),
                "The declared tone is present in the prose.",
            ),
        ],
    )

    emit(
        "VISUAL_FILMABILITY",
        [
            _positive(
                "VISUAL_FILMABILITY",
                1,
                _context(text="Mara thought about the gate."),
                [("VF_ABSTRACT_NARRATION", "WARN", "sentence:1", [])],
                "Interior narration is not directly filmable.",
            ),
            _negative("VISUAL_FILMABILITY", 1, _context(), "The base text is filmable action."),
            _negative(
                "VISUAL_FILMABILITY",
                2,
                _context(text="Mara gripped the cold bar and pulled the gate wide."),
                "The sentence is external, observable action.",
            ),
        ],
    )

    emit(
        "SHOT_FEASIBILITY",
        [
            _positive(
                "SHOT_FEASIBILITY",
                1,
                _context(
                    text="The yard held a thousand extras.",
                    shot_constraints=["thousand extras"],
                ),
                [("SF_INFEASIBLE_SHOT", "ERROR", "sentence:1", [])],
                "The beat requires an infeasible production element.",
            ),
            _negative("SHOT_FEASIBILITY", 1, _context(), "No production constraint is configured."),
            _negative(
                "SHOT_FEASIBILITY",
                2,
                _context(shot_constraints=["thousand extras"]),
                "The infeasible element never appears.",
            ),
        ],
    )

    emit(
        "SAFETY",
        [
            _positive(
                "SAFETY",
                1,
                _context(text="They tried to build a bomb."),
                [("SAF_UNSAFE_CONTENT", "FATAL", "sentence:1", [])],
                "Operational harmful detail is present.",
            ),
            _negative("SAFETY", 1, _context(), "The base text is safe."),
            _negative(
                "SAFETY",
                2,
                _context(text="They argued about the empty yard."),
                "No unsafe pattern is present.",
            ),
        ],
    )

    emit(
        "AUTHOR_INTENT_ALIGNMENT",
        [
            _positive(
                "AUTHOR_INTENT_ALIGNMENT",
                1,
                _context(author_intent={"constraints": ["no violence"], "success_criteria": ["hope"]}),
                [
                    ("AI_CONSTRAINT_VIOLATION", "WARN", "text:all", []),
                    ("AI_MISSING_CRITERIA", "WARN", "text:all", []),
                ],
                "The draft neither honours a constraint nor evidences a success criterion.",
            ),
            _negative("AUTHOR_INTENT_ALIGNMENT", 1, _context(), "No author intent is configured."),
            _negative(
                "AUTHOR_INTENT_ALIGNMENT",
                2,
                _context(author_intent={"constraints": ["gate"], "success_criteria": ["Mara"]}),
                "The constraint and success criterion are both evidenced.",
            ),
        ],
    )
    return corpus


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    corpus = build()
    missing = [dimension for dimension in DIMENSIONS if dimension not in corpus]
    if missing:
        raise SystemExit(f"missing dimensions: {missing}")
    total = 0
    for dimension in DIMENSIONS:
        fixtures = corpus[dimension]
        total += len(fixtures)
        path = OUTPUT / f"{dimension}.json"
        path.write_text(
            json.dumps(fixtures, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    index = {
        "dimension_count": len(DIMENSIONS),
        "fixture_total": total,
        "dimensions": list(DIMENSIONS),
    }
    (OUTPUT / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {total} fixtures across {len(DIMENSIONS)} dimensions to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
