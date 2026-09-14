"""Gold behaviour for durable persistent interactive play."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul import Action, PlayEngine
from hevi.creative.omodul.play import (
    ActionKind,
    Evidence,
    Relationship,
    TurnEffects,
)
from hevi.creative.oprim import StaleRevisionError
from hevi.obase.creative import InteractiveWorld, InventoryItem


def _world(project_id):
    return InteractiveWorld(
        project_id=project_id,
        title="Owned World",
        world_contract="stable",
        clock="turn",
    )


def test_turn_effects_accumulate_and_persist(tmp_path) -> None:
    project_id = uuid4()
    engine = PlayEngine()
    state = engine.start(_world(project_id), player_id="player", location="harbour").state
    path = tmp_path / "play-state.json"
    for turn in range(3):
        effects = None
        if turn == 0:
            effects = TurnEffects(
                inventory=(InventoryItem(item_id="harbour-key", quantity=1),),
                evidence=(
                    Evidence(
                        evidence_id="key-found",
                        statement="found the harbour key",
                        discovered_at_turn=0,
                    ),
                ),
                relationships=(Relationship(from_id="player", to_id="Mara", value=0.5),),
                visual_refs=("visual://harbour/key",),
            )
        elif turn == 1:
            effects = TurnEffects(
                inventory=(InventoryItem(item_id="harbour-key", quantity=2),),
                relationships=(Relationship(from_id="player", to_id="Mara", value=0.9),),
            )
        state, _ = engine.step(
            state, Action(kind=ActionKind.CHOICE, label=f"inspect-{turn}"), effects=effects
        )
        engine.persist_turn(path, state)
    restored = engine.restore(path)
    assert sum(item.quantity for item in restored.inventory) == 3
    assert restored.evidence[0].discovered_at_turn == 0
    assert restored.relationships[0].value == 0.9
    assert restored.visual_refs == ("visual://harbour/key",)
    assert restored.revision == 3


def test_stale_turn_persist_is_rejected(tmp_path) -> None:
    project_id = uuid4()
    engine = PlayEngine()
    state = engine.start(_world(project_id), player_id="player", location="harbour").state
    path = tmp_path / "play-state.json"
    first, _ = engine.step(state, Action(kind=ActionKind.CHOICE, label="first"))
    engine.persist_turn(path, first)
    second, _ = engine.step(first, Action(kind=ActionKind.CHOICE, label="second"))
    engine.persist_turn(path, second)
    with pytest.raises(StaleRevisionError):
        engine.persist_turn(path, first)
