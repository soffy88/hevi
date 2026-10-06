"""HEVI P6.5.2 — Grammar compatibility as a constraint model.

G-14 was that P6.3/P6.4 shipped vocabularies whose coherence intersection is a
**perfect diagonal**: 3 of 24 (style, visual-grammar) pairings were usable.
``archival_history``, ``future_tech`` and ``corporate_clean`` styles were dead, and
P6.4's ``commercial_clean`` grammar — the one meant for commercial work — had no
coherent partner at all.

The old model was equality: pair iff the three shared languages matched exactly.
That is what produced the diagonal. Two artefacts about the *same* visual tradition
rarely use identical vocabularies, so demanding identity over three channels at
once guarantees collapse.

The constraint model
--------------------
Coherence is now a set of small, single-channel rules with an explicit severity:

* a **hard** conflict on one channel refuses the pair
* a **soft** difference narrows the intent's flexibility rather than refusing it
* **unset** channels do not constrain

Each rule has one key and one channel, so rules compose, and each is independently
inspectable. ``documentary_realism`` (composition ``documentary``) and
``commercial_clean`` (composition ``presenter_centered``) now coexist under a soft
rule — an observed narrative frame genuinely *can* serve a presenter-centred shot
— where equality refused them outright.

Why constraints and not a whitelist
-----------------------------------
A whitelist is a pair list: 24 entries today, and every new style or grammar means
auditing every pair against every other. That is how whitelists rot, and it
encodes no *reason*. A constraint says *why* and composes: adding a fifth
composition value cannot silently invalidate rules about lighting, because no rule
mentions lighting.

Deliberately not invented
-------------------------
This module names **no** new visual language values. The vocabularies are P6.3's
(``Mood``, ``ColorLanguage``, ``CompositionLanguage``, ``TextureLanguage``,
``MotionLanguage``, ``LightingLanguage``). It adds
``EditingLanguage`` and ``CameraLanguage`` only because P6.4 ships grammars that
must be expressible, and those two vocabularies belong to P6.4 rather than to
P6.3. Recorded in the gap map.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p6.visual_grammar import CameraLanguage, EditingLanguage
from hevi.production.p6.visual_style.model import (
    ColorLanguage,
    CompositionLanguage,
    LightingLanguage,
    Mood,
    MotionLanguage,
    TextureLanguage,
)

# ── the channels compatibility is expressed over ────────────────────────
# Every value is a member of a P6.3 or P6.4 enum. `CHANNELS` is the complete set of
# things a compatibility rule may talk about, which is what makes an unconstrained
# pair explicit rather than accidental.

CHANNELS: frozenset[str] = frozenset(
    {
        "mood",
        "palette",
        "texture",
        "motion",
        "composition",
        "lighting",
        "camera",
        "editing",
    }
)

#: The three channels P6.3 and P6.4 both declare, i.e. the ones that previously
#: had to match for equality.
SHARED_CHANNELS: tuple[str, ...] = ("motion", "composition", "lighting")


class ConflictKind(StrEnum):
    """How a rule is applied.

    Three kinds, because the channels are not equally binding:

    ``AGREE``
        The two layers must declare the **same** value on this channel. The rule
        names the channel only — not a value — so it is one rule per channel
        rather than one per value. An earlier version of this model generated one
        ``HARD`` rule per value and compared both sides to that fixed value, which
        made every mismatched pair report N conflicts instead of 1.
    ``EXCLUDE``
        Value-specific: if one side is ``value`` and the other is anything else,
        the pair is incoherent. For exclusions that are genuinely absolute.
    ``FLEX``
        Values may differ. The pair is coherent; the intent is flagged flexible
        so downstream knows it has less room to work with.
    ``UNSET``
        The channel does not constrain this pairing, declared explicitly so
        ``list_rules()`` is a complete account of the policy's beliefs.
    """

    AGREE = "agree"
    EXCLUDE = "exclude"
    FLEX = "flex"
    UNSET = "unset"


class Severity(StrEnum):
    INFO = "info"
    ADVISORY = "advisory"
    BLOCKING = "blocking"


# ── the two artefacts under test ────────────────────────────────────────


@dataclass(frozen=True)
class VisualStyleDescriptor:
    """P6.3's contribution: how it looks."""

    style_id: str
    mood: Mood
    palette: ColorLanguage
    texture: TextureLanguage
    motion: MotionLanguage
    composition: CompositionLanguage
    lighting: LightingLanguage


@dataclass(frozen=True)
class VisualGrammarDescriptor:
    """P6.4's contribution: how it is shot and cut."""

    visual_grammar_id: str
    camera: CameraLanguage
    motion: MotionLanguage
    composition: CompositionLanguage
    lighting: LightingLanguage
    editing: EditingLanguage


@dataclass(frozen=True)
class CompatibilityRule:
    """One channel, one constraint, one key.

    The whole model is these. Single-channel by construction: a rule that
    constrained two channels at once would be two rules wearing a coat, and the
    channel-conflict counts in the gap map (``motion`` 15, ``composition`` 19,
    ``lighting`` 18 of 24) would be unrecoverable.
    """

    key: str
    kind: ConflictKind
    channel: str
    value: str | None = None
    severity: Severity = Severity.BLOCKING
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.kind is ConflictKind.UNSET:
            return
        if self.channel not in CHANNELS:
            raise ValueError(f"UNKNOWN_COMPATIBILITY_CHANNEL:{self.channel}")
        if self.kind is ConflictKind.EXCLUDE and not self.value:
            raise ValueError(f"EXCLUDE_RULE_WITHOUT_VALUE:{self.channel}")
        if self.kind is ConflictKind.AGREE and self.value is not None:
            raise ValueError(
                f"AGREE_RULE_MUST_NOT_PIN_A_VALUE:{self.channel}; AGREE compares the "
                "two sides with each other, so pinning a value would contradict itself"
            )

    def evaluate(self, left: str, right: str) -> str | None:
        """Return a message when this rule objects to the pair."""
        if self.kind is ConflictKind.UNSET:
            return None
        if self.kind is ConflictKind.AGREE:
            return None if left == right else (
                f"{self.channel.upper()}_DISAGREEMENT:{left}|{right}"
            )
        if self.kind is ConflictKind.EXCLUDE:
            if left == right:
                return None
            if left == self.value or right == self.value:
                return f"{self.channel.upper()}_EXCLUDED:{left}|{self.value}|{right}"
            return None
        return None if left == right else f"{self.channel.upper()}_FLEXIBLE:{left}|{right}"


@dataclass(frozen=True)
class CompatibilityDecision:
    """ALLOW or DENY, plus the reasons.

    A decision is never just a boolean: ``blocking`` says what refused the pair and
    ``advisory`` says what was stretched, so a DENY can be acted on rather than
    guessed at.
    """

    allowed: bool
    blocking: tuple[str, ...] = ()
    advisory: tuple[str, ...] = ()
    flexible_channels: tuple[str, ...] = ()
    rules_evaluated: int = 0

    @property
    def decision(self) -> str:
        return "ALLOW" if self.allowed else "DENY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "allowed": self.allowed,
            "blocking": list(self.blocking),
            "advisory": list(self.advisory),
            "flexible_channels": list(self.flexible_channels),
            "rules_evaluated": self.rules_evaluated,
        }


class GrammarCompatibilityPolicy:
    """ALLOW / DENY for a (style, visual-grammar) pair, from constraints alone.

    Holds rules keyed by a channel *value*. There is no key that names a product,
    and no key that enumerates pairs — so a new style or grammar is expressible
    without auditing it against every existing counterpart.
    """

    def __init__(self) -> None:
        self._rules: dict[str, CompatibilityRule] = {}
        self._order: list[str] = []
        #: (channel, value) pairs already covered by an EXCLUDE rule. Kept apart
        #: from `_rules`, which is keyed by rule key — the first version indexed
        #: `_rules` here and the guard could therefore never fire.
        self._exclusions: set[tuple[str, str]] = set()

    def add(self, rule: CompatibilityRule) -> CompatibilityRule:
        if rule.key in self._rules:
            raise ValueError(f"COMPATIBILITY_RULE_DUPLICATE:{rule.key}")
        if rule.kind is ConflictKind.EXCLUDE and rule.value is not None:
            clash = (rule.channel, rule.value)
            if clash in self._exclusions:
                raise ValueError(
                    f"COMPATIBILITY_RULE_CONFLICT:{rule.channel}={rule.value} already excluded"
                )
            self._exclusions.add(clash)
        self._rules[rule.key] = rule
        self._order.append(rule.key)
        return rule

    def get(self, key: str) -> CompatibilityRule | None:
        return self._rules.get(key)

    def list_rules(self) -> list[CompatibilityRule]:
        return [self._rules[k] for k in self._order]

    def list_keys(self) -> list[str]:
        return list(self._order)

    def evaluate(
        self,
        style: VisualStyleDescriptor,
        grammar: VisualGrammarDescriptor,
    ) -> CompatibilityDecision:
        """Evaluate every applicable rule. Blocking rules deny; soft ones advise."""
        left = _style_channel_values(style)
        right = _grammar_channel_values(grammar)
        blocking: list[str] = []
        advisory: list[str] = []
        flexible: list[str] = []
        evaluated = 0
        for key in self._order:
            rule = self._rules[key]
            channel = rule.channel
            if channel not in left or channel not in right:
                continue  # this rule's channel is not declared by both artefacts
            message = rule.evaluate(left[channel], right[channel])
            if message is None:
                continue
            evaluated += 1
            if rule.severity is Severity.BLOCKING:
                blocking.append(f"{key}:{message}")
            elif rule.severity is Severity.ADVISORY:
                advisory.append(f"{key}:{message}")
                flexible.append(channel)
            else:
                advisory.append(f"{key}:{message}")
        return CompatibilityDecision(
            allowed=not blocking,
            blocking=tuple(blocking),
            advisory=tuple(advisory),
            flexible_channels=tuple(sorted(set(flexible))),
            rules_evaluated=evaluated,
        )

    def decide(
        self,
        style: VisualStyleDescriptor,
        grammar: VisualGrammarDescriptor,
    ) -> str:
        return self.evaluate(style, grammar).decision

    def allowed_pairs(self) -> list[tuple[str, str]]:
        """Every coherent pair, computed from the rules rather than stored."""
        from hevi.production.p6.visual_grammar import BUILTIN_VISUAL_GRAMMARS
        from hevi.production.p6.visual_style.registry import BUILTIN_VISUAL_STYLES

        pairs: list[tuple[str, str]] = []
        for style in BUILTIN_VISUAL_STYLES:
            sd = descriptor_for_style(style)
            for grammar in BUILTIN_VISUAL_GRAMMARS:
                gd = descriptor_for_grammar(grammar)
                if self.evaluate(sd, gd).allowed:
                    pairs.append((sd.style_id, gd.visual_grammar_id))
        return sorted(set(pairs))

    def to_dict(self) -> dict[str, Any]:
        return {
            key: {
                "kind": rule.kind.value,
                "channel": rule.channel,
                "value": rule.value,
                "severity": rule.severity.value,
                "rationale": rule.rationale,
            }
            for key, rule in self._rules.items()
        }


def _style_channel_values(style: VisualStyleDescriptor) -> dict[str, str]:
    return {
        "mood": style.mood.value,
        "palette": style.palette.value,
        "texture": style.texture.value,
        "motion": style.motion.value,
        "composition": style.composition.value,
        "lighting": style.lighting.value,
    }


def _grammar_channel_values(grammar: VisualGrammarDescriptor) -> dict[str, str]:
    return {
        "motion": grammar.motion.value,
        "composition": grammar.composition.value,
        "lighting": grammar.lighting.value,
        "camera": grammar.camera.value,
        "editing": grammar.editing.value,
    }


def descriptor_for_style(style: Any) -> VisualStyleDescriptor:
    """Project any :class:`VisualStyleGrammar` onto the channel vocabulary."""
    return VisualStyleDescriptor(
        style_id=style.id,
        mood=style.mood,
        palette=style.color_language,
        texture=style.texture_language,
        motion=style.motion_language,
        composition=style.composition_language,
        lighting=style.lighting_language,
    )


def descriptor_for_grammar(grammar: Any) -> VisualGrammarDescriptor:
    """Project any :class:`VisualGrammar` onto the channel vocabulary."""
    return VisualGrammarDescriptor(
        visual_grammar_id=grammar.visual_grammar_id,
        camera=grammar.camera_language,
        motion=grammar.motion_language,
        composition=grammar.composition_language,
        lighting=grammar.lighting_language,
        editing=grammar.editing_language,
    )


def _unrestrained(channel: str) -> CompatibilityRule:
    """A rule that never objects, declared for auditability.

    Keeping the "nothing to say about X" entries explicit is what lets
    ``evaluate()`` skip cleanly and keeps ``list_rules()`` a complete account of
    what the policy believes rather than a partial one.
    """
    return CompatibilityRule(
        key=f"channel:{channel}=any",
        kind=ConflictKind.UNSET,
        channel=channel,
        rationale=f"no {channel} constraint is declared; the channel is not a gate",
    )


def build_default_policy() -> GrammarCompatibilityPolicy:
    """The shipped constraint set.

    One ``AGREE`` gate, one absolute ``EXCLUDE``, and the rest explicitly
    unconstrained or flexible.

    Why only motion gates hard
    --------------------------
    The G-14 diagonal existed because agreement was required on motion *and*
    lighting *and* composition simultaneously. Those three channels are correlated
    across P6.3 and P6.4 — each style's (motion, lighting) combination maps to
    exactly one grammar — so requiring agreement on two of them reproduces the
    diagonal no matter how the rules are written.

    Of the three, **motion** is the only one where disagreement is a genuine
    contradiction rather than extra work: ``MotionLanguage`` means the same thing
    in both layers (the felt quality of movement), so a restrained look under an
    energetic strategy is two different intentions, not one intention expressed
    twice.

    Lighting and composition are *work*, not incoherence. A natural-light look can
    be lit for, a documentary frame can carry a performer-centred shot. Those are
    flagged flexible so downstream knows to compensate, rather than refused
    outright. The one absolute exclusion is ``infographic``, where the two framing
    logics have no common room at all.
    """
    policy = GrammarCompatibilityPolicy()
    for channel in sorted(CHANNELS):
        policy.add(_unrestrained(channel))

    policy.add(
        CompatibilityRule(
            key="motion:agree",
            kind=ConflictKind.AGREE,
            channel="motion",
            severity=Severity.BLOCKING,
            rationale=(
                "motion means the same thing in both layers; a mismatch is two "
                "different intentions rather than one stated twice"
            ),
        )
    )
    policy.add(
        CompatibilityRule(
            key="lighting:flex",
            kind=ConflictKind.FLEX,
            channel="lighting",
            severity=Severity.ADVISORY,
            rationale=(
                "lighting can be addressed in grade; disagreement costs fidelity, "
                "not coherence"
            ),
        )
    )
    policy.add(
        CompatibilityRule(
            key="composition:flex",
            kind=ConflictKind.FLEX,
            channel="composition",
            severity=Severity.ADVISORY,
            rationale="a differing frame is usable but less specific",
        )
    )
    policy.add(
        CompatibilityRule(
            key="composition:exclude=infographic",
            kind=ConflictKind.EXCLUDE,
            channel="composition",
            value=CompositionLanguage.INFOGRAPHIC.value,
            severity=Severity.BLOCKING,
            rationale=(
                "an infographic frame has no room for an observed or "
                "performer-centred shot; the two framing logics exclude each other"
            ),
        )
    )
    return policy


#: The single compatibility authority.
GRAMMAR_COMPATIBILITY_POLICY: GrammarCompatibilityPolicy = build_default_policy()


__all__ = [
    "CHANNELS",
    "GRAMMAR_COMPATIBILITY_POLICY",
    "SHARED_CHANNELS",
    "CompatibilityDecision",
    "CompatibilityRule",
    "ConflictKind",
    "GrammarCompatibilityPolicy",
    "Severity",
    "VisualGrammarDescriptor",
    "VisualStyleDescriptor",
    "build_default_policy",
    "descriptor_for_grammar",
    "descriptor_for_style",
]
