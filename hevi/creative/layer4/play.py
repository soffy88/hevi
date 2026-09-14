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
    visual_refs: tuple[str, ...] = ()


class TurnEffects(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory: tuple[InventoryItem, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    visual_refs: tuple[str, ...] = ()


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
    visual_refs: tuple[str, ...] = ()


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

    def step(
        self,
        state: PlayState,
        action: Action,
        *,
        effects: TurnEffects | None = None,
    ) -> tuple[PlayState, TurnResult]:
        applied = effects or TurnEffects()
        turn = Turn(number=state.clock.value, action=action)
        event = WorldEvent(turn=turn.number, description=action.label)
        next_state = state.model_copy(
            update={
                "revision": state.revision + 1,
                "clock": WorldClock(value=state.clock.value + 1, unit=state.clock.unit),
                "inventory": _merge_inventory(state.inventory, applied.inventory),
                "evidence": (*state.evidence, *applied.evidence),
                "relationships": _merge_relationships(
                    state.relationships, applied.relationships
                ),
                "events": (*state.events, event),
                "turn_history": (*state.turn_history, turn),
                "visual_refs": (*state.visual_refs, *applied.visual_refs),
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
            visual_refs=applied.visual_refs,
        )
        return next_state, result

    def persist_turn(self, path: str | Path, state: PlayState) -> None:
        destination = Path(path)
        expected = state.revision - 1 if destination.exists() and state.revision else None
        persist_model(path, state, expected_previous_revision=expected)

    def restore(self, path: str | Path) -> PlayState:
        return restore_model(path, PlayState)


def _merge_inventory(
    current: tuple[InventoryItem, ...], added: tuple[InventoryItem, ...]
) -> tuple[InventoryItem, ...]:
    totals: dict[str, int] = {item.item_id: item.quantity for item in current}
    for item in added:
        totals[item.item_id] = totals.get(item.item_id, 0) + item.quantity
    return tuple(InventoryItem(item_id=key, quantity=value) for key, value in totals.items())


def _merge_relationships(
    current: tuple[Relationship, ...], added: tuple[Relationship, ...]
) -> tuple[Relationship, ...]:
    values: dict[tuple[str, str], float] = {
        (item.from_id, item.to_id): item.value for item in current
    }
    for item in added:
        values[(item.from_id, item.to_id)] = item.value
    return tuple(
        Relationship(from_id=pair[0], to_id=pair[1], value=value)
        for pair, value in values.items()
    )


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
    "TurnEffects",
    "TurnResult",
    "WorldClock",
    "WorldContract",
    "WorldEvent",
]
