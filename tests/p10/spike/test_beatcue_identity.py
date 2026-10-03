"""G0.2-A2: BeatCue stable identity — backward compat + provenance hook."""

from hevi.cinematic.shot_intelligence.models import BeatCue, ShotPlan, ShotRecipe
from hevi.cinematic.shot_intelligence.persistence import (
    deserialize_plan,
    replay_plan,
    serialize_plan,
)


def _plan_with_cue(cue: BeatCue) -> ShotPlan:
    return ShotPlan(
        line="test",
        shots=(ShotRecipe(id="s1", shot_type="wide", framing="wide"),),
        beat_cues=(cue,),
    )


def test_positional_construction_unchanged():
    cue = BeatCue(2.5)
    assert (cue.time_s, cue.kind, cue.strength) == (2.5, "beat", 1.0)
    assert cue.cue_id == "" and cue.creative_cue_ref == ""


def test_old_payload_without_ids_deserializes():
    plan = _plan_with_cue(BeatCue(2.5))
    payload = serialize_plan(plan)
    payload["beat_cues"][0].pop("cue_id")
    payload["beat_cues"][0].pop("creative_cue_ref")
    revived = deserialize_plan(payload)
    assert revived.beat_cues[0].cue_id == ""
    assert revived.beat_cues[0].time_s == 2.5


def test_ids_roundtrip_and_provenance_hook():
    cue = BeatCue(47.18, kind="revelation", strength=0.9, cue_id="cue:C21", creative_cue_ref="ccue:C21")
    revived = replay_plan(_plan_with_cue(cue))
    assert revived.beat_cues[0].cue_id == "cue:C21"
    assert revived.beat_cues[0].creative_cue_ref == "ccue:C21"
    # Decision→Cue→Shot 追踪挂接点存在
    assert revived.beat_cues[0].cue_id
