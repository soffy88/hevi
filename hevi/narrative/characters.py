"""Character authority and scene snapshots."""

from __future__ import annotations

from hevi.narrative.models import Character, CharacterState, StoryBible


def character_authority(bible: StoryBible, character_id: str) -> Character:
    for character in bible.characters:
        if character.id == character_id:
            return character
    raise KeyError(f"unknown character: {character_id}")


def scene_character_state(bible: StoryBible, state: CharacterState) -> CharacterState:
    character = character_authority(bible, state.character_id)
    allowed = set(character.knowledge_state)
    if not set(state.knowledge).issubset(allowed):
        raise ValueError(f"character knowledge exceeds authority: {state.character_id}")
    return state
