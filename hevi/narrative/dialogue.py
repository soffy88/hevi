"""Dialogue intent checks; generated dialogue remains downstream content."""

from __future__ import annotations

from hevi.narrative.models import Character, DialogueIntent


def validate_dialogue_intents(intents: tuple[DialogueIntent, ...], characters: tuple[Character, ...]) -> list[str]:
    known = {character.id for character in characters}
    return [f"unknown speaker: {intent.speaker}" for intent in intents if intent.speaker not in known]
