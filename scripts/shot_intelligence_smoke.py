"""Planning-only smoke for the opt-in Shot Intelligence boundary."""

from __future__ import annotations

import json
import os

from hevi.cinematic.shot_intelligence.integration import plan_for_line
from hevi.cinematic.shot_intelligence.models import ShotIntent
from hevi.cinematic.shot_intelligence.projections import (
    to_ffmpeg,
    to_generated_video_prompt,
    to_remotion,
)
from hevi.cinematic.shot_intelligence.validator import validate_shot_plan


def main() -> int:
    os.environ["SHOT_INTELLIGENCE_ENABLED"] = "1"
    lines = ("kinetic_promo", "explainer", "shorts_clip")
    output: dict[str, object] = {}
    for line in lines:
        intents = [
            ShotIntent(line, "opening", "establishing", "subject"),
            ShotIntent(line, "proof", "action", "subject", narration_present=True),
        ]
        plan = plan_for_line(line, intents)
        assert plan is not None
        qa = validate_shot_plan(plan)
        output[line] = {"shots": len(plan.shots), "qa": qa.status, "remotion": to_remotion(plan), "ffmpeg": to_ffmpeg(plan), "prompts": to_generated_video_prompt(plan)}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
