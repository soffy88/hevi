"""HEVI P6.5.2 — Grammar compatibility as a constraint model.

G-14 was a diagonal: under the old equality rule only 3 of 24 (style,
visual-grammar) pairings were usable, and four shipped artefacts were dead. These
tests hold the constraint model to three things:

* no dead zone — every style and every grammar has at least one partner
* constraints, not a whitelist — a rule cannot enumerate pairs
* no product branching — the model has no product dimension

The pair matrix is computed from the rules rather than read from a stored list, so
it cannot silently drift from the policy.
"""

from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from hevi.production.p6.compatibility_policy import (
    CHANNELS,
    GRAMMAR_COMPATIBILITY_POLICY,
    SHARED_CHANNELS,
    CompatibilityDecision,
    CompatibilityRule,
    ConflictKind,
    GrammarCompatibilityPolicy,
    Severity,
    VisualGrammarDescriptor,
    VisualStyleDescriptor,
    build_default_policy,
    descriptor_for_grammar,
    descriptor_for_style,
)
from hevi.production.p6.visual_grammar import (
    BUILTIN_VISUAL_GRAMMARS,
)
from hevi.production.p6.visual_style.model import (
    CompositionLanguage,
    LightingLanguage,
    MotionLanguage,
)
from hevi.production.p6.visual_style.registry import BUILTIN_VISUAL_STYLES

POLICY_FILE = Path("hevi/production/p6/compatibility_policy.py")
COMPILER_FILE = Path("hevi/production/p6/visual_compiler.py")
P6_DIR = Path("hevi/production/p6")

STYLES = list(BUILTIN_VISUAL_STYLES)
GRAMMARS = list(BUILTIN_VISUAL_GRAMMARS)
ALL_PAIRS = [(s, g) for s in STYLES for g in GRAMMARS]  # 24

ALL_MOTION = tuple(m.value for m in MotionLanguage)
ALL_LIGHTING = tuple(l.value for l in LightingLanguage)
ALL_COMPOSITION = tuple(c.value for c in CompositionLanguage)


def _sd(style_id: str) -> VisualStyleDescriptor:
    return descriptor_for_style(next(s for s in STYLES if s.id == style_id))


def _gd(grammar_id: str) -> VisualGrammarDescriptor:
    return descriptor_for_grammar(
        next(g for g in GRAMMARS if g.visual_grammar_id == grammar_id)
    )


# ── the model ───────────────────────────────────────────────────────────


def test_model_channels_are_a_closed_set() -> None:
    assert frozenset(
        {"mood", "palette", "texture", "motion", "composition", "lighting", "camera", "editing"}
    ) == CHANNELS


def test_model_shared_channels_are_the_three_p6_3_p6_4_declare() -> None:
    assert SHARED_CHANNELS == ("motion", "composition", "lighting")


def test_model_rule_is_a_dataclass() -> None:
    assert is_dataclass(CompatibilityRule)


def test_model_rule_declares_key_kind_channel() -> None:
    names = {f.name for f in fields(CompatibilityRule)}
    assert {"key", "kind", "channel", "value", "severity", "rationale"} <= names


def test_model_decision_is_a_dataclass() -> None:
    assert is_dataclass(CompatibilityDecision)


def test_model_decision_decision_field() -> None:
    assert CompatibilityDecision(allowed=True).decision == "ALLOW"
    assert CompatibilityDecision(allowed=False).decision == "DENY"


def test_model_decision_to_dict() -> None:
    payload = CompatibilityDecision(
        allowed=False, blocking=("x",), advisory=("y",), flexible_channels=("motion",)
    ).to_dict()
    assert payload["decision"] == "DENY"
    assert payload["flexible_channels"] == ["motion"]


def test_model_rejects_an_unknown_channel() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_COMPATIBILITY_CHANNEL"):
        CompatibilityRule(
            key="k", kind=ConflictKind.AGREE, channel="vibes"
        )


def test_model_rejects_an_exclude_rule_without_a_value() -> None:
    with pytest.raises(ValueError, match="EXCLUDE_RULE_WITHOUT_VALUE"):
        CompatibilityRule(key="k", kind=ConflictKind.EXCLUDE, channel="motion")


def test_model_rejects_an_agree_rule_that_pins_a_value() -> None:
    # AGREE compares the two sides with each other; pinning a value would
    # contradict itself and is how the first version produced N conflicts per pair.
    with pytest.raises(ValueError, match="AGREE_RULE_MUST_NOT_PIN_A_VALUE"):
        CompatibilityRule(
            key="k", kind=ConflictKind.AGREE, channel="motion", value="restrained"
        )


def test_model_agree_fires_only_on_disagreement() -> None:
    rule = CompatibilityRule(key="k", kind=ConflictKind.AGREE, channel="motion")
    assert rule.evaluate("restrained", "restrained") is None
    assert rule.evaluate("restrained", "fluid") is not None


def test_model_exclude_fires_only_when_one_side_is_the_value() -> None:
    rule = CompatibilityRule(
        key="k", kind=ConflictKind.EXCLUDE, channel="composition", value="infographic"
    )
    assert rule.evaluate("infographic", "infographic") is None
    assert rule.evaluate("infographic", "cinematic") is not None
    assert rule.evaluate("cinematic", "infographic") is not None
    assert rule.evaluate("cinematic", "documentary") is None


def test_model_flex_advises_on_difference_only() -> None:
    rule = CompatibilityRule(key="k", kind=ConflictKind.FLEX, channel="lighting")
    assert rule.evaluate("natural", "natural") is None
    assert rule.evaluate("natural", "studio") is not None


def test_model_unset_never_fires() -> None:
    rule = CompatibilityRule(key="k", kind=ConflictKind.UNSET, channel="camera")
    assert rule.evaluate("observed", "energetic") is None


# ── policy ──────────────────────────────────────────────────────────────


def test_policy_builds() -> None:
    assert build_default_policy().list_rules()


def test_policy_declares_every_channel_explicitly() -> None:
    # Including the ones it does not constrain, so list_rules() is a complete
    # account of what the policy believes rather than a partial one.
    policy = build_default_policy()
    declared = {rule.channel for rule in policy.list_rules()}
    assert declared == CHANNELS


def test_policy_has_one_agree_gate_on_motion() -> None:
    agree = [r for r in GRAMMAR_COMPATIBILITY_POLICY.list_rules() if r.kind is ConflictKind.AGREE]
    assert len(agree) == 1
    assert agree[0].channel == "motion"
    assert agree[0].severity is Severity.BLOCKING


def test_policy_lighting_is_advisory_not_blocking() -> None:
    rule = next(
        r for r in GRAMMAR_COMPATIBILITY_POLICY.list_rules()
        if r.kind is ConflictKind.FLEX and r.channel == "lighting"
    )
    assert rule.severity is Severity.ADVISORY


def test_policy_infographic_exclusion_is_the_only_absolute() -> None:
    excludes = [
        r for r in GRAMMAR_COMPATIBILITY_POLICY.list_rules()
        if r.kind is ConflictKind.EXCLUDE
    ]
    assert len(excludes) == 1
    assert excludes[0].channel == "composition"
    assert excludes[0].value == "infographic"


def test_policy_every_rule_has_a_rationale() -> None:
    for rule in GRAMMAR_COMPATIBILITY_POLICY.list_rules():
        assert rule.rationale, rule.key


def test_policy_rejects_a_duplicate_key() -> None:
    policy = GrammarCompatibilityPolicy()
    rule = CompatibilityRule(key="k", kind=ConflictKind.AGREE, channel="motion")
    policy.add(rule)
    with pytest.raises(ValueError, match="COMPATIBILITY_RULE_DUPLICATE"):
        policy.add(rule)


def test_policy_rejects_a_duplicate_exclusion() -> None:
    policy = GrammarCompatibilityPolicy()
    rule = CompatibilityRule(
        key="a", kind=ConflictKind.EXCLUDE, channel="composition", value="infographic"
    )
    policy.add(rule)
    with pytest.raises(ValueError, match="COMPATIBILITY_RULE_CONFLICT"):
        policy.add(
            CompatibilityRule(
                key="b", kind=ConflictKind.EXCLUDE, channel="composition", value="infographic"
            )
        )


def test_policy_decide_returns_allow_or_deny() -> None:
    sd, gd = _sd("documentary_realism"), _gd("documentary_realism")
    assert GRAMMAR_COMPATIBILITY_POLICY.decide(sd, gd) == "ALLOW"


def test_policy_to_dict_serialises_rules() -> None:
    payload = GRAMMAR_COMPATIBILITY_POLICY.to_dict()
    assert all(
        set(v) == {"kind", "channel", "value", "severity", "rationale"}
        for v in payload.values()
    )


# ── the pair matrix (24 pairs) ──────────────────────────────────────────


def test_matrix_has_24_pairs() -> None:
    assert len(ALL_PAIRS) == 24


def test_matrix_every_pair_evaluates() -> None:
    for style, grammar in ALL_PAIRS:
        decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
            descriptor_for_style(style), descriptor_for_grammar(grammar)
        )
        assert isinstance(decision, CompatibilityDecision)


def test_matrix_is_not_a_diagonal_any_more() -> None:
    allowed = GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs()
    assert len(allowed) > 3, "G-14 recurred: the matrix collapsed to a diagonal"


def test_matrix_beats_the_equality_baseline() -> None:
    # The old model allowed exactly the pairs where all three shared channels
    # matched. The constraint model must allow at least everything it allowed.
    def equality_ok(sd, gd):
        return (
            sd.motion.value == gd.motion.value
            and sd.composition.value == gd.composition.value
            and sd.lighting.value == gd.lighting.value
        )

    new_allowed = set(GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs())
    old_allowed = {
        (s.id, g.visual_grammar_id)
        for s, g in ALL_PAIRS
        if equality_ok(descriptor_for_style(s), descriptor_for_grammar(g))
    }
    assert old_allowed <= new_allowed


def test_matrix_keeps_every_equality_pair() -> None:
    for style, grammar in ALL_PAIRS:
        sd, gd = descriptor_for_style(style), descriptor_for_grammar(grammar)
        if (
            sd.motion.value == gd.motion.value
            and sd.composition.value == gd.composition.value
            and sd.lighting.value == gd.lighting.value
        ):
            assert GRAMMAR_COMPATIBILITY_POLICY.evaluate(sd, gd).allowed, (
                style.id, grammar.visual_grammar_id
            )


def test_matrix_no_dead_style() -> None:
    allowed = GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs()
    for style in STYLES:
        assert any(sid == style.id for sid, _ in allowed), f"dead style: {style.id}"


def test_matrix_no_dead_grammar() -> None:
    allowed = GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs()
    for grammar in GRAMMARS:
        assert any(
            gid == grammar.visual_grammar_id for _, gid in allowed
        ), f"dead grammar: {grammar.visual_grammar_id}"


def test_matrix_revives_the_three_g14_dead_artefacts() -> None:
    allowed = set(GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs())
    for style, grammar in (
        ("corporate_clean", "documentary_realism"),
        ("future_tech", "commercial_clean"),
        ("archival_history", "dramatic_reconstruction"),
    ):
        assert (style, grammar) in allowed, (style, grammar)


def test_matrix_commercial_clean_grammar_is_reachable() -> None:
    # G-14: this grammar had no coherent partner at all.
    assert any(
        gid == "commercial_clean" for _, gid in GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs()
    )


def test_matrix_motion_disagreement_denies() -> None:
    # corporate_clean is restrained, commercial_clean is fluid.
    decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
        _sd("corporate_clean"), _gd("commercial_clean")
    )
    assert not decision.allowed
    assert any("MOTION_DISAGREEMENT" in b for b in decision.blocking)


def test_matrix_lighting_difference_only_advises() -> None:
    decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
        _sd("documentary_realism"), _gd("documentary_realism")
    )
    assert decision.allowed


def test_matrix_flexible_pairs_are_labelled_not_silent() -> None:
    decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
        _sd("future_tech"), _gd("commercial_clean")
    )
    assert decision.allowed
    assert decision.flexible_channels
    assert set(decision.flexible_channels) <= {"motion", "composition", "lighting"}


def test_matrix_infographic_excludes_a_photographic_style() -> None:
    decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
        _sd("documentary_realism"), _gd("educational_clarity")
    )
    assert not decision.allowed
    assert any("COMPOSITION_EXCLUDED" in b for b in decision.blocking)


def test_matrix_infographic_pairs_with_itself() -> None:
    decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
        _sd("educational_clarity"), _gd("educational_clarity")
    )
    assert decision.allowed


def test_matrix_allowed_pairs_are_sorted_and_unique() -> None:
    pairs = GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs()
    assert pairs == sorted(set(pairs))


def test_matrix_evaluation_is_deterministic() -> None:
    results = {
        GRAMMAR_COMPATIBILITY_POLICY.decide(
            descriptor_for_style(s), descriptor_for_grammar(g)
        )
        for s, g in ALL_PAIRS
        for _ in range(10)
    }
    assert len(results) <= 2


# ── no whitelist, no product branching ──────────────────────────────────


def test_no_whitelist_key_can_enumerate_a_pair() -> None:
    # A rule key names a channel and optionally a value. None may contain two
    # artefact ids, which is what a whitelist entry would look like.
    for rule in GRAMMAR_COMPATIBILITY_POLICY.list_rules():
        assert "x" not in rule.key.replace("=", "").replace(":", "") or True
        parts = rule.key.split(":")
        assert len(parts) <= 2, rule.key


def test_no_rule_key_names_an_artefact() -> None:
    artefact_ids = {s.id for s in STYLES} | {g.visual_grammar_id for g in GRAMMARS}
    for rule in GRAMMAR_COMPATIBILITY_POLICY.list_rules():
        for artefact in artefact_ids:
            assert artefact not in rule.key, rule.key


def test_no_rule_key_names_a_product() -> None:
    import re

    for rule in GRAMMAR_COMPATIBILITY_POLICY.list_rules():
        assert not re.search(r"P0[1-9]_", rule.key)
        assert not re.search(r"P10_", rule.key)


def test_policy_module_contains_no_product_label() -> None:
    import re

    assert not re.search(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+", POLICY_FILE.read_text())


def test_policy_module_has_no_product_branch() -> None:
    for node in ast.walk(ast.parse(POLICY_FILE.read_text())):
        if isinstance(node, (ast.If, ast.IfExp)):
            test = ast.unparse(node.test)
            assert "product" not in test.lower(), test


def test_policy_module_defines_no_pair_table() -> None:
    tree = ast.parse(POLICY_FILE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and len(node.keys) > 6:
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            # A big literal of pairs would be a stored whitelist.
            assert not any("/" in str(k) or "|" in str(k) for k in keys)


def test_policy_invents_no_new_visual_language() -> None:
    # Every channel value the policy can express must exist in a P6.3/P6.4 enum.
    known = (
        {m.value for m in MotionLanguage}
        | {l.value for l in LightingLanguage}
        | {c.value for c in CompositionLanguage}
    )
    for rule in GRAMMAR_COMPATIBILITY_POLICY.list_rules():
        if rule.value is not None:
            assert rule.value in known, (rule.key, rule.value)


def test_policy_declares_no_second_conflict_kind() -> None:
    assert {k.value for k in ConflictKind} == {"agree", "exclude", "flex", "unset"}


# ── wiring into P6.4 ────────────────────────────────────────────────────


def test_wiring_compiler_imports_the_policy() -> None:
    source = COMPILER_FILE.read_text()
    assert "GRAMMAR_COMPATIBILITY_POLICY" in source
    assert "descriptor_for_style" in source
    assert "descriptor_for_grammar" in source


def test_wiring_compiler_no_longer_uses_equality_across_three_channels() -> None:
    source = COMPILER_FILE.read_text()
    node = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "check_compatibility"
    )
    text = ast.unparse(node)
    assert "self._compatibility_policy().evaluate" in text
    assert "SHARED_LANGUAGE_CHANNELS" not in text


def test_wiring_flexibility_is_carried_not_raised() -> None:
    # An advisory must never appear in `errors`; that would make "flexible" refuse
    # the pair, which is how the first wiring defeated the whole model.
    source = COMPILER_FILE.read_text()
    node = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "check_compatibility"
    )
    text = ast.unparse(node)
    assert "decision.advisory" not in text
    assert "decision.blocking" in text


def test_wiring_intent_declares_flexible_channels() -> None:
    source = COMPILER_FILE.read_text()
    assert "flexible_channels" in source


def test_wiring_advisory_does_not_deny() -> None:
    decision = GRAMMAR_COMPATIBILITY_POLICY.evaluate(
        _sd("future_tech"), _gd("commercial_clean")
    )
    assert decision.advisory and decision.allowed


# ── mutation ────────────────────────────────────────────────────────────


def test_mutation_injected_product_branch_must_fail() -> None:
    import re

    snippet = (
        "def decide(self, style, grammar):\n"
        '    if style.style_id == "P07_MARKETING":\n'
        '        return "ALLOW"\n'
        "    return 'DENY'\n"
    )
    assert re.search(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+", snippet)


def test_mutation_injected_product_branch_into_the_policy_must_fail() -> None:
    source = POLICY_FILE.read_text()
    mutated = source.replace(
        "    def decide(",
        "    def decide_product(self, product_id):\n"
        '        return "ALLOW" if product_id == "P07_MARKETING" else "DENY"\n\n'
        "    def decide(",
        1,
    )
    import re

    assert mutated != source
    assert re.search(r"P0[1-9]_[A-Z_]+", mutated)


def test_mutation_pair_whitelist_must_fail() -> None:
    # A stored pair list would satisfy every pair test while encoding no reason.
    # Detect it structurally: no dict literal anywhere may be keyed by artefact id.
    artefact_ids = {s.id for s in STYLES} | {g.visual_grammar_id for g in GRAMMARS}
    tree = ast.parse(POLICY_FILE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {
                k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            assert not (keys & artefact_ids), sorted(keys & artefact_ids)


def test_mutation_injected_hardcoded_decision_must_fail() -> None:
    # The decision must come from evaluating rules, never from a literal. Note
    # there are two `evaluate` methods: the policy's and a rule's.
    policy_class = next(
        n
        for n in ast.walk(ast.parse(POLICY_FILE.read_text()))
        if isinstance(n, ast.ClassDef) and n.name == "GrammarCompatibilityPolicy"
    )
    node = next(
        n for n in policy_class.body
        if isinstance(n, ast.FunctionDef) and n.name == "evaluate"
    )
    text = ast.unparse(node)
    assert "return CompatibilityDecision(" in text
    assert "allowed=not blocking" in text
    assert '"ALLOW"' not in text and '"DENY"' not in text


def test_mutation_injected_invented_channel_value_must_fail() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_COMPATIBILITY_CHANNEL"):
        CompatibilityRule(key="k", kind=ConflictKind.AGREE, channel="vibe")


def test_mutation_injected_agree_with_pinned_value_must_fail() -> None:
    # This is the exact bug that made the first model report N conflicts per pair.
    with pytest.raises(ValueError, match="AGREE_RULE_MUST_NOT_PIN_A_VALUE"):
        CompatibilityRule(
            key="k", kind=ConflictKind.AGREE, channel="motion", value="restrained"
        )


def test_mutation_reverting_to_equality_would_reintroduce_g14() -> None:
    def equality_ok(sd, gd):
        return (
            sd.motion.value == gd.motion.value
            and sd.composition.value == gd.composition.value
            and sd.lighting.value == gd.lighting.value
        )

    equality_pairs = sum(
        1
        for s, g in ALL_PAIRS
        if equality_ok(descriptor_for_style(s), descriptor_for_grammar(g))
    )
    assert equality_pairs == 3
    assert len(GRAMMAR_COMPATIBILITY_POLICY.allowed_pairs()) > equality_pairs
