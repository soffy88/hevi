"""Extensible genre rules, progression blueprints, and fatigue checks.

A genre is not metadata.  Each blueprint drives a deterministic production plan
(beat sequence, scene density, pacing targets, dialogue expectations) and a
content gate (required patterns, forbidden patterns, fatigue vocabulary).
Planning the same brief under two genres therefore yields structurally
different plans, and auditing the same text under two profiles yields different
findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from hevi.obase.creative import GenreProfile, GenreRule


class GenreValidationError(ValueError):
    """Raised when a genre profile or rule is not usable."""


@dataclass(frozen=True)
class GenreBlueprint:
    name: str
    description: str
    pacing_profile: str
    beat_sequence: tuple[str, ...]
    scene_count: int
    target_words_per_chapter: int
    dialogue_target: float
    action_target: float
    required_patterns: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    fatigue_lexicon: tuple[str, ...]
    rules: tuple[GenreRule, ...]


def _rule(name: str, requirement: str, severity: str = "SOFT") -> GenreRule:
    return GenreRule(name=name, requirement=requirement, severity=severity)  # type: ignore[arg-type]


BLUEPRINTS: tuple[GenreBlueprint, ...] = (
    GenreBlueprint(
        name="mystery",
        description="Clue-forward investigation with withheld information.",
        pacing_profile="measured",
        beat_sequence=("setup", "clue", "complication", "revelation", "turn"),
        scene_count=5,
        target_words_per_chapter=2800,
        dialogue_target=0.40,
        action_target=0.10,
        required_patterns=("clue", "suspect"),
        forbidden_patterns=("coincidence", "spell"),
        fatigue_lexicon=("suddenly", "somehow"),
        rules=(
            _rule("fair_play", "every clue is visible before the solution", "HARD"),
            _rule("no_coincidence", "resolutions must not rely on coincidence", "HARD"),
        ),
    ),
    GenreBlueprint(
        name="thriller",
        description="Escalating pressure with deadlines and pursuit.",
        pacing_profile="accelerating",
        beat_sequence=("hook", "threat", "pursuit", "setback", "climax", "turn"),
        scene_count=6,
        target_words_per_chapter=2400,
        dialogue_target=0.25,
        action_target=0.45,
        required_patterns=("deadline", "pursuit"),
        forbidden_patterns=("boredom", "spell"),
        fatigue_lexicon=("suddenly", "just", "literally"),
        rules=(
            _rule("deadline", "each act carries a clock", "HARD"),
            _rule("escalation", "stakes rise every chapter", "HARD"),
        ),
    ),
    GenreBlueprint(
        name="romance",
        description="Relationship-first emotional progression.",
        pacing_profile="slow-burn",
        beat_sequence=("meet", "spark", "misunderstand", "rupture", "turn", "resolve"),
        scene_count=4,
        target_words_per_chapter=2600,
        dialogue_target=0.55,
        action_target=0.05,
        required_patterns=("meet", "misunderstand"),
        forbidden_patterns=("instalove", "spell"),
        fatigue_lexicon=("smiled", "breathed", "suddenly"),
        rules=(
            _rule("agency", "both leads make active choices", "HARD"),
            _rule("earned_turn", "the rupture is earned by prior beats", "SOFT"),
        ),
    ),
    GenreBlueprint(
        name="horror",
        description="Dread, isolation, and escalation of the unknown.",
        pacing_profile="dread",
        beat_sequence=("normal", "unease", "isolation", "threat", "turn", "aftermath"),
        scene_count=5,
        target_words_per_chapter=2500,
        dialogue_target=0.15,
        action_target=0.20,
        required_patterns=("isolation", "threat"),
        forbidden_patterns=("jump scare only", "spell"),
        fatigue_lexicon=("dark", "cold", "suddenly"),
        rules=(
            _rule("dread_over_gore", "sustain dread instead of only gore", "SOFT"),
            _rule("isolation", "remove the safety net before the threat", "HARD"),
        ),
    ),
    GenreBlueprint(
        name="action",
        description="Kinetic set pieces with minimal exposition.",
        pacing_profile="kinetic",
        beat_sequence=("cold_open", "chase", "fight", "breather", "climax", "turn", "coda"),
        scene_count=7,
        target_words_per_chapter=2200,
        dialogue_target=0.10,
        action_target=0.60,
        required_patterns=("chase", "fight"),
        forbidden_patterns=("exposition dump", "spell"),
        fatigue_lexicon=("explosion", "suddenly", "just"),
        rules=(
            _rule("show_the_stakes", "action communicates stakes physically", "HARD"),
            _rule("no_exposition", "avoid exposition dumps between set pieces", "HARD"),
        ),
    ),
    GenreBlueprint(
        name="literary",
        description="Image and theme first, plot second.",
        pacing_profile="reflective",
        beat_sequence=("image", "interior", "turn", "echo"),
        scene_count=3,
        target_words_per_chapter=3200,
        dialogue_target=0.20,
        action_target=0.02,
        required_patterns=("image", "theme"),
        forbidden_patterns=("cliche", "spell"),
        fatigue_lexicon=("very", "really", "just"),
        rules=(
            _rule("theme", "every scene refracts the theme", "HARD"),
            _rule("no_cliche", "avoid received phrasing", "HARD"),
        ),
    ),
    GenreBlueprint(
        name="fantasy",
        description="World rules with explicit costs and quest progression.",
        pacing_profile="quest",
        beat_sequence=("call", "crossing", "trial", "cost", "turn", "climax", "return"),
        scene_count=6,
        target_words_per_chapter=3000,
        dialogue_target=0.30,
        action_target=0.30,
        required_patterns=("world rule", "cost"),
        forbidden_patterns=("deus ex machina", "spell"),
        fatigue_lexicon=("ancient", "prophecy", "suddenly"),
        rules=(
            _rule("cost", "magic or power always has a cost", "HARD"),
            _rule("no_deus_ex_machina", "the resolution emerges from established rules", "HARD"),
        ),
    ),
    GenreBlueprint(
        name="science-fiction",
        description="Constraint-driven procedural extrapolation.",
        pacing_profile="procedural",
        beat_sequence=("premise", "constraint", "experiment", "consequence", "turn", "resolution"),
        scene_count=5,
        target_words_per_chapter=2900,
        dialogue_target=0.35,
        action_target=0.25,
        required_patterns=("constraint", "consequence"),
        forbidden_patterns=("handwave", "spell"),
        fatigue_lexicon=("quantum", "nebula", "suddenly"),
        rules=(
            _rule("one_rule", "one speculative rule, applied consistently", "HARD"),
            _rule("consequence", "every solution creates a new constraint", "HARD"),
        ),
    ),
)

BLUEPRINTS_BY_NAME: dict[str, GenreBlueprint] = {item.name: item for item in BLUEPRINTS}


@dataclass(frozen=True)
class GenrePlan:
    genre: str
    pacing_profile: str
    beats: tuple[str, ...]
    scene_count: int
    target_words_per_chapter: int
    dialogue_target: float
    action_target: float
    required_patterns: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    fatigue_lexicon: tuple[str, ...]
    brief: str

    def signature(self) -> tuple[object, ...]:
        return (
            self.pacing_profile,
            self.beats,
            self.scene_count,
            self.target_words_per_chapter,
            rounded(self.dialogue_target),
            rounded(self.action_target),
        )


def rounded(value: float) -> float:
    return round(value, 3)


class GenreModule:
    """Genre blueprints, extensible profiles, planning, and content gates."""

    def __init__(self) -> None:
        self._registered: dict[tuple[UUID, str], GenreProfile] = {}

    # -- catalogue ---------------------------------------------------------
    @staticmethod
    def list_builtin() -> tuple[str, ...]:
        return tuple(item.name for item in BLUEPRINTS)

    @staticmethod
    def blueprint(name: str) -> GenreBlueprint:
        try:
            return BLUEPRINTS_BY_NAME[name]
        except KeyError as exc:
            raise GenreValidationError(f"GENRE_UNKNOWN:{name}") from exc

    def profile(self, *, project_id: UUID, name: str) -> GenreProfile:
        blueprint = self.blueprint(name)
        return GenreProfile(
            project_id=project_id,
            name=blueprint.name,
            rules=blueprint.rules,
            forbidden_patterns=blueprint.forbidden_patterns,
            pacing_profile=blueprint.pacing_profile,
            fatigue_lexicon=blueprint.fatigue_lexicon,
        )

    # -- extensibility -----------------------------------------------------
    def create(
        self,
        *,
        project_id: UUID,
        name: str,
        rules: tuple[GenreRule, ...] = (),
        forbidden_patterns: tuple[str, ...] = (),
        pacing_profile: str | None = None,
        fatigue_lexicon: tuple[str, ...] = (),
    ) -> GenreProfile:
        profile = GenreProfile(
            project_id=project_id,
            name=name,
            rules=rules,
            forbidden_patterns=forbidden_patterns,
            pacing_profile=pacing_profile,
            fatigue_lexicon=fatigue_lexicon,
        )
        self.validate(profile)
        if (project_id, profile.name) in self._registered:
            raise GenreValidationError(f"GENRE_DUPLICATE:{profile.name}")
        self._registered[(project_id, profile.name)] = profile
        return profile

    def copy(self, *, source: GenreProfile, project_id: UUID, new_name: str) -> GenreProfile:
        """Copy a built-in or registered profile before editing it."""

        if (project_id, new_name) in self._registered:
            raise GenreValidationError(f"GENRE_DUPLICATE:{new_name}")
        blueprint = BLUEPRINTS_BY_NAME.get(source.name)
        rules = blueprint.rules if blueprint is not None else source.rules
        copied = GenreProfile(
            project_id=project_id,
            name=new_name,
            rules=rules,
            forbidden_patterns=source.forbidden_patterns,
            pacing_profile=source.pacing_profile,
            fatigue_lexicon=source.fatigue_lexicon,
        )
        self.validate(copied)
        self._registered[(project_id, new_name)] = copied
        return copied

    @staticmethod
    def validate(profile: GenreProfile) -> None:
        if not profile.name.strip():
            raise GenreValidationError("GENRE_EMPTY_NAME")
        seen: set[str] = set()
        for rule in profile.rules:
            if not rule.name.strip() or not rule.requirement.strip():
                raise GenreValidationError("GENRE_INVALID_RULE")
            if rule.name in seen:
                raise GenreValidationError(f"GENRE_DUPLICATE_RULE:{rule.name}")
            seen.add(rule.name)
        for pattern in profile.forbidden_patterns:
            if not pattern.strip():
                raise GenreValidationError("GENRE_EMPTY_FORBIDDEN_PATTERN")

    def registered(self, project_id: UUID) -> tuple[GenreProfile, ...]:
        return tuple(
            profile for (owner, _), profile in self._registered.items() if owner == project_id
        )

    # -- planning ----------------------------------------------------------
    def plan(
        self,
        profile: GenreProfile,
        *,
        brief: str,
        chapter_count: int = 1,
    ) -> GenrePlan:
        blueprint = BLUEPRINTS_BY_NAME.get(profile.name)
        if blueprint is not None:
            beats = blueprint.beat_sequence
            scene_count = blueprint.scene_count
            words = blueprint.target_words_per_chapter
            dialogue = blueprint.dialogue_target
            action = blueprint.action_target
            required = blueprint.required_patterns
            pacing = blueprint.pacing_profile
        else:
            beats = tuple(rule.name for rule in profile.rules) or ("setup", "turn")
            scene_count = max(1, len(beats))
            words = 2000
            dialogue = 0.3
            action = 0.2
            required = ()
            pacing = profile.pacing_profile or "custom"
        if chapter_count > 1:
            words = max(800, words * chapter_count // max(1, chapter_count))
        return GenrePlan(
            genre=profile.name,
            pacing_profile=pacing,
            beats=beats,
            scene_count=scene_count,
            target_words_per_chapter=words,
            dialogue_target=dialogue,
            action_target=action,
            required_patterns=required,
            forbidden_patterns=profile.forbidden_patterns,
            fatigue_lexicon=profile.fatigue_lexicon,
            brief=brief,
        )

    # -- content gate ------------------------------------------------------
    def audit(self, profile: GenreProfile, text: str) -> tuple[GenreFinding, ...]:
        findings: list[GenreFinding] = []
        lowered = text.casefold()
        findings.extend(
            GenreFinding("FORBIDDEN_PATTERN", "ERROR", pattern)
            for pattern in profile.forbidden_patterns
            if pattern and pattern.casefold() in lowered
        )
        for word in profile.fatigue_lexicon:
            count = len(re.findall(rf"\b{re.escape(word)}\b", lowered))
            if count > 3:
                findings.append(GenreFinding("FATIGUE_WORD", "WARN", f"{word}:{count}"))
        blueprint = BLUEPRINTS_BY_NAME.get(profile.name)
        if blueprint is not None:
            findings.extend(
                GenreFinding("REQUIRED_PATTERN_MISSING", "WARN", pattern)
                for pattern in blueprint.required_patterns
                if pattern not in lowered
            )
            observed = _dialogue_ratio(text)
            if observed is not None and observed < blueprint.dialogue_target - 0.2:
                findings.append(
                    GenreFinding(
                        "DIALOGUE_EXPECTATION",
                        "WARN",
                        f"{profile.name}:{observed:.2f}<{blueprint.dialogue_target:.2f}",
                    )
                )
        return tuple(findings)


@dataclass(frozen=True)
class GenreFinding:
    code: str
    severity: str
    message: str


def _dialogue_ratio(text: str) -> float | None:
    if not text.strip():
        return None
    quoted = sum(len(match) for match in re.findall(r"[\"“].*?[\"”]", text, re.DOTALL))
    return min(1.0, quoted / len(text))


__all__ = [
    "BLUEPRINTS",
    "BLUEPRINTS_BY_NAME",
    "GenreBlueprint",
    "GenreFinding",
    "GenreModule",
    "GenrePlan",
    "GenreValidationError",
]
