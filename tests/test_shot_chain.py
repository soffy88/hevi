"""Contract tests for story.shot_chain (offline, deterministic).

Fixtures are invented for these tests only: a lighthouse keeper
tending a lamp room, three plain invented shots. No real plot,
person, or reference text is reused. No media is generated.
"""

import json

import pytest

from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.shot_chain as shot_chain


def _shots():
    return [
        {
            "shot_id": "S01",
            "scene_id": "lamp-room",
            "character_ids": ["K01"],
            "action": "Keeper trims the lamp wick.",
            "duration": 5,
        },
        {
            "shot_id": "S02",
            "scene_id": "lamp-room",
            "character_ids": ["K01"],
            "action": "Keeper lights the lamp.",
            "duration": 5,
        },
        {
            "shot_id": "S03",
            "scene_id": "lamp-room",
            "character_ids": ["K01"],
            "action": "Keeper watches the beam sweep the water.",
            "duration": 6,
        },
    ]


def test_three_shot_chain_links_to_immediate_predecessor():
    result = shot_chain.build_chain(_shots())
    chain = result["chain"]
    assert [link["shot_id"] for link in chain] == ["S01", "S02", "S03"]
    assert chain[0]["prev_shot_id"] is None
    assert chain[0]["tail_frame_ref"] is None
    assert chain[0]["first_frame_ref"] is None
    assert chain[1]["prev_shot_id"] == "S01"
    assert chain[1]["tail_frame_ref"] == {
        "kind": "tail_frame",
        "from_shot_id": "S01",
    }
    assert chain[2]["prev_shot_id"] == "S02"
    assert chain[2]["tail_frame_ref"] == {
        "kind": "tail_frame",
        "from_shot_id": "S02",
    }
    assert shot_chain.validate_chain(chain) == []


def test_first_frame_refs_attached_per_shot_only():
    refs = {"S02": {"kind": "image", "ref": "frame-s02.png"}}
    result = shot_chain.build_chain(_shots(), first_frame_refs=refs)
    chain = result["chain"]
    assert chain[0]["first_frame_ref"] is None
    assert chain[1]["first_frame_ref"] == {
        "kind": "image",
        "ref": "frame-s02.png",
    }
    assert chain[2]["first_frame_ref"] is None


def test_single_shot_chain_has_no_tail_frame():
    result = shot_chain.build_chain(_shots()[:1])
    chain = result["chain"]
    assert len(chain) == 1
    assert chain[0]["shot_id"] == "S01"
    assert chain[0]["prev_shot_id"] is None
    assert chain[0]["tail_frame_ref"] is None
    assert shot_chain.validate_chain(chain) == []


def test_empty_shots_raises():
    with pytest.raises(CapabilityError):
        shot_chain.build_chain([])


def test_missing_shot_id_raises():
    shots = _shots()
    del shots[1]["shot_id"]
    with pytest.raises(CapabilityError):
        shot_chain.build_chain(shots)


def test_duplicate_shot_id_raises():
    shots = _shots()
    shots[2]["shot_id"] = "S01"
    with pytest.raises(CapabilityError):
        shot_chain.build_chain(shots)


def test_validate_flags_first_shot_tail_frame_as_error():
    chain = [
        {
            "shot_id": "S01",
            "prev_shot_id": None,
            "tail_frame_ref": {"kind": "tail_frame", "from_shot_id": "S00"},
            "first_frame_ref": None,
        },
        {
            "shot_id": "S02",
            "prev_shot_id": "S01",
            "tail_frame_ref": {"kind": "tail_frame", "from_shot_id": "S01"},
            "first_frame_ref": None,
        },
    ]
    issues = shot_chain.validate_chain(chain)
    assert len(issues) == 1
    assert issues[0]["shot_id"] == "S01"
    assert issues[0]["severity"] == "error"
    assert issues[0]["code"] == "first_shot_has_tail_frame"
    assert issues[0]["message"]


def test_validate_warns_on_missing_middle_tail_frame():
    chain = shot_chain.build_chain(_shots())["chain"]
    chain[1]["tail_frame_ref"] = None
    issues = shot_chain.validate_chain(chain)
    assert len(issues) == 1
    assert issues[0]["shot_id"] == "S02"
    assert issues[0]["severity"] == "warning"
    assert issues[0]["code"] == "missing_tail_frame"


def test_validate_flags_tail_frame_pointing_to_non_previous_as_error():
    chain = shot_chain.build_chain(_shots())["chain"]
    chain[2]["tail_frame_ref"] = {"kind": "tail_frame", "from_shot_id": "S01"}
    issues = shot_chain.validate_chain(chain)
    assert len(issues) == 1
    assert issues[0]["shot_id"] == "S03"
    assert issues[0]["severity"] == "error"
    assert issues[0]["code"] == "tail_frame_not_previous"


def test_chain_output_is_json_serializable():
    result = shot_chain.build_chain(
        _shots(), first_frame_refs={"S01": {"kind": "image", "ref": "frame-s01.png"}}
    )
    text = json.dumps(result)
    assert json.loads(text) == result


def test_validate_accepts_build_chain_result_dict():
    result = shot_chain.build_chain(_shots())
    assert shot_chain.validate_chain(result) == []
