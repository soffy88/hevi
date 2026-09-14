"""Skills provide knowledge and policy, never authority or side effects."""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["RegisteredSkill", "SkillRegistry", "SkillSafetyError"]
