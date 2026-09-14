"""Durable turn-based interactive world primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.oprim.persistence import persist_model, restore_model
from hevi.obase.creative import InteractiveWorld, InventoryItem


class ActionKind(StrEnum):
    CHOICE = "CHOICE"
    FREE = "FREE"


class WorldContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    rules: tuple[str, ...] = ()


class WorldClock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: int = Field(default=0, ge=0)
    unit: str = "turn"


class PlayerState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    player_id: str
    location: str
    relationship_values: tuple[tuple[str, float], ...] = ()


class CharacterAgentState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: str
    location: str
    mood: str | None = None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    statement: str
    discovered_at_turn: int = Field(ge=0)


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_id: str
    to_id: str
    value: float = Field(default=0.0, ge=-1.0, le=1.0)


class WorldEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    turn: int = Field(ge=0)
    description: str


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ActionKind
    label: str
    target: str | None = None


class FreeAction(Action):
    kind: ActionKind = ActionKind.FREE
    text: str = Field(min_length=1)


class HUDState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    location: str
    objective: str | None = None
    inventory_count: int = Field(default=0, ge=0)


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: UUID = Field(default_factory=uuid4)
    number: int = Field(ge=0)
    action: Action


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn: Turn
    state_revision: int = Field(ge=0)
    narrative: str
    events: tuple[WorldEvent, ...] = ()
    hud: HUDState


class PlayState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_id: UUID = Field(default_factory=uuid4)
    world_id: UUID
    revision: int = Field(default=0, ge=0)
    clock: WorldClock = Field(default_factory=WorldClock)
    player: PlayerState
    agents: tuple[CharacterAgentState, ...] = ()
    inventory: tuple[InventoryItem, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    events: tuple[WorldEvent, ...] = ()
    turn_history: tuple[Turn, ...] = ()


@dataclass(frozen=True)
class PlayStart:
    world: InteractiveWorld
    state: PlayState


class PlayEngine:
    def start(self, world: InteractiveWorld, *, player_id: str, location: str) -> PlayStart:
        state = PlayState(
            world_id=world.object_id,
            player=PlayerState(player_id=player_id, location=location),
        )
        return PlayStart(world, state)

    def step(self, state: PlayState, action: Action) -> tuple[PlayState, TurnResult]:
        turn = Turn(number=state.clock.value, action=action)
        event = WorldEvent(turn=turn.number, description=action.label)
        next_state = state.model_copy(
            update={
                "revision": state.revision + 1,
                "clock": WorldClock(value=state.clock.value + 1, unit=state.clock.unit),
                "events": (*state.events, event),
                "turn_history": (*state.turn_history, turn),
            }
        )
        result = TurnResult(
            turn=turn,
            state_revision=next_state.revision,
            narrative=action.label,
            events=(event,),
            hud=HUDState(
                location=next_state.player.location,
                inventory_count=sum(item.quantity for item in next_state.inventory),
            ),
        )
        return next_state, result

    def persist_turn(self, path: str | Path, state: PlayState) -> None:
        destination = Path(path)
        expected = state.revision - 1 if destination.exists() and state.revision else None
        persist_model(path, state, expected_previous_revision=expected)

    def restore(self, path: str | Path) -> PlayState:
        return restore_model(path, PlayState)


__all__ = [
    "Action",
    "ActionKind",
    "CharacterAgentState",
    "Evidence",
    "FreeAction",
    "HUDState",
    "PlayEngine",
    "PlayStart",
    "PlayState",
    "PlayerState",
    "Relationship",
    "Turn",
    "TurnResult",
    "WorldClock",
    "WorldContract",
    "WorldEvent",
]
