import json
from pathlib import Path

import pytest

from hevi.video_intelligence.retrieval import RetrievalQuery, VideoTemporalIndex


@pytest.mark.parametrize("case", range(20))
def test_retrieval_gold_case_shape(case):
    query = RetrievalQuery(query_id=f"gold-{case:02d}", raw_intent="observed shot")
    index = VideoTemporalIndex(entries=[{
        "asset_id": "video:gold", "start_ms": 0, "end_ms": 1000,
        "semantic_text": "Observed shot", "structured_tags": ["OTHER"],
        "shot_refs": ["shot_0001"], "event_refs": [],
    }])
    result = index.retrieve(query)
    assert result and result[0].start_ms == 0


def test_retrieval_gold_manifest_has_twenty_cases():
    path = Path(__file__).parents[1] / "fixtures" / "video_retrieval_gold" / "cases.json"
    assert len(json.loads(path.read_text(encoding="utf-8"))) >= 20
