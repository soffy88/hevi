"""Contract tests for the playworld capabilities (play.world_init / play.world_step).

Offline and deterministic: the narrator is a test double injected into the
engine, and the capability path supplies narrator output as params.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.playworld import register_playworld_capabilities_once
from hevi.playworld import engine

register_playworld_capabilities_once()

WORLD_PARAMS = {
    "title": "雾港来信",
    "setting": "一座常年起雾的北方港口小城，1997 年",
    "characters": [{"name": "阿澈", "description": "十七岁的邮差学徒"}],
    "starting_location": "老邮局门口",
    "opening_narration": "雾里传来汽笛声，一封没有署名的信躺在台阶上。",
    "opening_choices": [
        {"id": "pick", "label": "捡起那封信"},
        {"id": "wait", "label": "留在原地等雾散"},
    ],
    "opening_image_prompt": "foggy northern harbour town, a letter on post office steps",
}


def _init(tmp_path: Path) -> Path:
    world = tmp_path / "world.json"
    cap = caps.get("play.world_init")
    result = cap.render_safe(
        {**WORLD_PARAMS, "world_path": str(world)}, tmp_path / "init-out",
        duration=1.0, aspect="9:16", seed=1,
    )
    assert result.qa["world_path"] == str(world)
    assert result.qa["turn"] == 0
    assert result.sha256
    return world


def test_playworld_capabilities_registered_and_listable() -> None:
    names = caps.names()
    assert "play.world_init" in names
    assert "play.world_step" in names
    listed = [c.name for c in caps.list(kind="line")]
    assert "play.world_init" in listed
    assert "play.world_step" in listed
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for name in ("play.world_init", "play.world_step"):
        assert by_name[name].get("description"), name


def test_world_init_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("play.world_init")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "o", duration=1.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {**WORLD_PARAMS, "world_path": str(tmp_path / "w.json"), "bogus": 1},
            tmp_path / "o", duration=1.0, aspect="9:16", seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {**WORLD_PARAMS, "world_path": str(tmp_path / "w.json"), "opening_choices": []},
            tmp_path / "o", duration=1.0, aspect="9:16", seed=1,
        )


def test_world_init_then_step_advances_state_and_turn(tmp_path: Path) -> None:
    world = _init(tmp_path)
    state = engine.load_world(world)
    assert state["turn"] == 0
    assert state["location"] == "老邮局门口"
    assert state["characters"][0]["name"] == "阿澈"

    cap = caps.get("play.world_step")
    result = cap.render_safe(
        {
            "world_path": str(world),
            "choice_id": "pick",
            "narration": "信封上只有一行字：别让汽笛响第三次。阿澈把信塞进口袋。",
            "choices": [{"id": "run", "label": "跑向码头"}],
            "image_prompt": "boy postman holding an unsigned letter, fog",
            "state_delta": {
                "flags": {"has_letter": True},
                "items_add": ["无名信"],
                "relationships": {"阿澈": {"老邮差": "起疑"}},
            },
        },
        tmp_path / "step-out", duration=1.0, aspect="9:16", seed=2,
    )
    assert result.qa["turn"] == 1
    assert result.qa["image_prompt"] == "boy postman holding an unsigned letter, fog"
    assert result.qa["choices"] == [{"id": "run", "label": "跑向码头"}]

    state = engine.load_world(world)
    assert state["turn"] == 1
    assert state["flags"]["has_letter"] is True
    assert state["items"] == ["无名信"]
    assert state["relationships"]["阿澈"]["老邮差"] == "起疑"
    assert state["log"][-1]["action"] == "捡起那封信"  # choice_id resolved to its label
    assert len(state["log"]) == 2

    snapshot = Path(result.qa["snapshot"])
    assert snapshot.is_file()
    snap_payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert snap_payload["turn"] == 1


def test_engine_step_with_injected_fake_narrator(tmp_path: Path) -> None:
    world = _init(tmp_path)
    seen: dict[str, object] = {}

    def fake_narrator(state, action_text):
        seen["action"] = action_text
        seen["turn_before"] = state["turn"]
        return {
            "narration": f"你选择了「{action_text}」，雾更浓了。",
            "choices": [{"id": "go", "label": "继续向前"}],
            "state_delta": {"location": "雾桥"},
            # no image_prompt: engine auto-composes the hook
        }

    outcome = engine.step_world(world, action="环顾四周", narrator_fn=fake_narrator)
    assert seen == {"action": "环顾四周", "turn_before": 0}
    assert outcome["turn"] == 1
    assert outcome["image_prompt"]  # auto-composed, non-empty
    assert "雾桥" in outcome["image_prompt"]
    assert engine.load_world(world)["location"] == "雾桥"

    outcome2 = engine.step_world(world, choice_id="go", narrator_fn=fake_narrator)
    assert outcome2["turn"] == 2
    assert engine.load_world(world)["turn"] == 2


def test_step_rejects_unknown_choice_and_missing_action(tmp_path: Path) -> None:
    world = _init(tmp_path)

    def narrator(state, action_text):  # pragma: no cover - must not be reached
        raise AssertionError("narrator should not run")

    with pytest.raises(CapabilityError):
        engine.step_world(world, choice_id="nope", narrator_fn=narrator)
    with pytest.raises(CapabilityError):
        engine.step_world(world, narrator_fn=narrator)

    cap = caps.get("play.world_step")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"world_path": str(world), "narration": "x", "choices": []},
            tmp_path / "o", duration=1.0, aspect="9:16", seed=1,
        )


def test_step_rejects_malformed_narrator_output(tmp_path: Path) -> None:
    world = _init(tmp_path)
    with pytest.raises(CapabilityError):
        engine.step_world(world, action="走", narrator_fn=lambda s, a: {})
    with pytest.raises(CapabilityError):
        engine.step_world(
            world, action="走",
            narrator_fn=lambda s, a: {"narration": "x", "choices": [], "state_delta": {"bogus": 1}},
        )
    # failed steps must not advance the world
    assert engine.load_world(world)["turn"] == 0


def test_world_init_refuses_overwrite_and_deleted_world_breaks_step(tmp_path: Path) -> None:
    world = _init(tmp_path)
    cap = caps.get("play.world_init")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {**WORLD_PARAMS, "world_path": str(world)}, tmp_path / "o2",
            duration=1.0, aspect="9:16", seed=1,
        )

    world.unlink()
    assert not world.exists(), "contract: deleting the artefact must break verification"
    step = caps.get("play.world_step")
    with pytest.raises(CapabilityError):
        step.render_safe(
            {"world_path": str(world), "action": "走", "narration": "x", "choices": []},
            tmp_path / "o3", duration=1.0, aspect="9:16", seed=1,
        )
