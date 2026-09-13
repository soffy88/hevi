import json
from pathlib import Path


def test_reel_and_quality_gold_manifests_have_twenty_cases():
    root = Path(__file__).parents[1] / "fixtures"
    for name in ("video_reel_gold", "video_quality_gold"):
        assert len(json.loads((root / name / "cases.json").read_text(encoding="utf-8"))) >= 20
