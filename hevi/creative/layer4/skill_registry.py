"""Skills provide knowledge and policy, never authority or side effects."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from hevi.obase.creative import CreativeSkill


class SkillSafetyError(PermissionError):
    """A skill attempted to claim a forbidden capability."""


@dataclass(frozen=True)
class RegisteredSkill:
    skill: CreativeSkill
    handler: str


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, RegisteredSkill] = {}

    def register(self, skill: CreativeSkill, *, handler: str) -> None:
        if skill.can_write_state or skill.can_bypass_gate:
            raise SkillSafetyError("skills cannot write state or bypass quality gates")
        if skill.name in self._skills:
            raise ValueError(f"skill already registered: {skill.name}")
        self._skills[skill.name] = RegisteredSkill(skill, handler)

    def resolve(self, name: str) -> RegisteredSkill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"skill not found: {name}") from exc

    def list_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))


DEFAULT_SKILL_NAMES = (
    "long-form-writing",
    "long-form-audit",
    "commercial-short-fiction",
    "interactive-play",
    "script-writing",
    "storyboarding",
    "interactive-film",
    "translation-localization",
    "manuscript-analysis",
    "market-research",
    "import-reconstruction",
    "cover-direction",
    "writing-naturalness",
    "genre-expertise",
    "creative-research",
)


def default_skill(name: str, project_id: UUID) -> CreativeSkill:
    if name not in DEFAULT_SKILL_NAMES:
        raise KeyError(name)
    return CreativeSkill(
        object_id=uuid4(),
        project_id=project_id,
        name=name,
        knowledge_refs=(),
        policy_refs=(),
        can_write_state=False,
        can_bypass_gate=False,
    )


__all__ = [
    "DEFAULT_SKILL_NAMES",
    "RegisteredSkill",
    "SkillRegistry",
    "SkillSafetyError",
    "default_skill",
]
