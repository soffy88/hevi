from hevi.cinematic.shot_intelligence.beat_sync import beat_projection, cues_from_times
from hevi.cinematic.shot_intelligence.models import ShotIntent
from hevi.cinematic.shot_intelligence.projections import (
    to_ffmpeg,
    to_generated_video_prompt,
    to_remotion,
)
from hevi.cinematic.shot_intelligence.selector import ShotSelector
from hevi.cinematic.shot_intelligence.sequence import SequencePlanner
from hevi.cinematic.shot_intelligence.validator import validate_shot_plan


def _intents(line: str = "kinetic_promo") -> list[ShotIntent]:
    return [
        ShotIntent(line, "open", "establishing", "subject", target_duration_s=3),
        ShotIntent(line, "action", "action", "subject", target_duration_s=3),
        ShotIntent(line, "close", "cta", "subject", target_duration_s=2, beat_map=cues_from_times([0.0, 1.0])),
    ]


def test_selector_is_deterministic_and_renderer_free() -> None:
    selector = ShotSelector()
    first = selector.plan(_intents())
    second = selector.plan(_intents())
    assert first == second
    assert all(shot.provenance for shot in first.shots)


def test_sequence_and_visual_qa_are_machine_readable() -> None:
    result = SequencePlanner().plan(_intents())
    qa = validate_shot_plan(result.plan)
    assert qa.status in {"PASS", "WARN"}
    assert isinstance(result.diagnostics, tuple)


def test_beat_and_renderer_projections_do_not_mutate_canonical_plan() -> None:
    plan = ShotSelector().plan(_intents())
    before = plan
    assert beat_projection(plan)["cut_points"]
    assert to_remotion(plan)["renderer"] == "remotion"
    assert to_ffmpeg(plan)["renderer"] == "ffmpeg"
    assert to_generated_video_prompt(plan)
    assert plan == before

