"""Genre behaviour gate: the same brief must plan differently per genre."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul.genre import (
    BLUEPRINTS,
    GenreModule,
    GenreValidationError,
)
from hevi.obase.creative import GenreRule

BRIEF = "A locked harbour and a missing key"


@pytest.fixture
def module() -> GenreModule:
    return GenreModule()


def test_eight_builtin_profiles(module: GenreModule) -> None:
    names = module.list_builtin()
    assert len(names) >= 8
    assert len(set(names)) == len(names)


def test_same_brief_plans_differently_per_genre(module: GenreModule) -> None:
    project_id = uuid4()
    signatures = set()
    for name in module.list_builtin():
        profile = module.profile(project_id=project_id, name=name)
        plan = module.plan(profile, brief=BRIEF)
        signatures.add(plan.signature())
    assert len(signatures) == len(module.list_builtin())


def test_genre_changes_pacing_density_and_dialogue(module: GenreModule) -> None:
    project_id = uuid4()
    action = module.plan(module.profile(project_id=project_id, name="action"), brief=BRIEF)
    literary = module.plan(module.profile(project_id=project_id, name="literary"), brief=BRIEF)
    assert action.action_target > literary.action_target
    assert action.dialogue_target < literary.dialogue_target
    assert action.scene_count != literary.scene_count
    assert action.beats != literary.beats


def test_genre_audit_effect_on_the_same_text(module: GenreModule) -> None:
    project_id = uuid4()
    text = "A spell lit the gate. The clue was a suspect."
    vectors = {
        name: tuple(
            sorted(
                f"{finding.code}:{finding.message}"
                for finding in module.audit(module.profile(project_id=project_id, name=name), text)
            )
        )
        for name in module.list_builtin()
    }
    assert len(set(vectors.values())) >= 2


def test_forbidden_pattern_gate(module: GenreModule) -> None:
    project_id = uuid4()
    profile = module.profile(project_id=project_id, name="mystery")
    findings = module.audit(profile, "A spell opens the gate.")
    assert any(
        finding.code == "FORBIDDEN_PATTERN" and finding.message == "spell" for finding in findings
    )
    clean = module.audit(profile, "A clause opens the gate.")
    assert not any(finding.code == "FORBIDDEN_PATTERN" for finding in clean)


def test_fatigue_lexicon_gate(module: GenreModule) -> None:
    project_id = uuid4()
    profile = module.profile(project_id=project_id, name="mystery")
    findings = module.audit(profile, "Suddenly a. Suddenly b. Suddenly c. Suddenly d.")
    assert any(finding.code == "FATIGUE_WORD" for finding in findings)


def test_required_pattern_gate(module: GenreModule) -> None:
    project_id = uuid4()
    profile = module.profile(project_id=project_id, name="action")
    findings = module.audit(profile, "A quiet conversation at a desk.")
    assert any(finding.code == "REQUIRED_PATTERN_MISSING" for finding in findings)


def test_profiles_are_project_scoped(module: GenreModule) -> None:
    project_id = uuid4()
    other = uuid4()
    module.create(project_id=project_id, name="house-style", pacing_profile="measured")
    assert all(item.project_id == project_id for item in module.registered(project_id=project_id))
    assert module.registered(project_id=other) == ()


def test_invalid_rule_fails_closed(module: GenreModule) -> None:
    project_id = uuid4()
    with pytest.raises(GenreValidationError):
        module.create(
            project_id=project_id,
            name="broken",
            rules=(GenreRule(name="", requirement=""),),
        )
    with pytest.raises(GenreValidationError):
        module.create(project_id=project_id, name="")
    with pytest.raises(GenreValidationError):
        module.create(project_id=project_id, name="empty-pattern", forbidden_patterns=(" ",))


def test_duplicate_profile_is_rejected(module: GenreModule) -> None:
    project_id = uuid4()
    module.create(project_id=project_id, name="house-style")
    with pytest.raises(GenreValidationError):
        module.create(project_id=project_id, name="house-style")


def test_copy_before_edit(module: GenreModule) -> None:
    project_id = uuid4()
    base = module.profile(project_id=project_id, name="mystery")
    copied = module.copy(source=base, project_id=project_id, new_name="mystery-noir")
    assert copied.name == "mystery-noir"
    assert copied.rules == base.rules
    assert copied.forbidden_patterns == base.forbidden_patterns


def test_unknown_genre_fails_closed(module: GenreModule) -> None:
    with pytest.raises(GenreValidationError):
        module.blueprint("not-a-genre")


def test_blueprints_declare_rules_and_gates() -> None:
    for blueprint in BLUEPRINTS:
        assert blueprint.beat_sequence
        assert blueprint.required_patterns
        assert blueprint.forbidden_patterns
        assert blueprint.rules
