import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import hevi.capabilities as caps
from hevi.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_capabilities_registered_and_listed():
    expected = [
        "stickman.topic_scout",
        "stickman.structure_clone",
        "stickman.proposal",
        "stickman.render_local",
        "stickman.flow_pack",
        "stickman.flow_import",
    ]
    all_names = caps.names()
    for name in expected:
        assert name in all_names
        cap = caps.get(name)
        assert cap.line == "stickman"
        assert cap.kind == "shot"
        assert "16:9" in cap.aspects


def test_capability_topic_scout_render(tmp_path):
    cap = caps.get("stickman.topic_scout")
    csv_data = "channel_name,title,views,subscribers,monthly_uploads\n极简,冰块沉浮,500000,50000,2\n"
    res = cap.render({"source": csv_data}, tmp_path, duration=60.0, aspect="16:9", seed=1)
    assert res.qa["topics_count"] == 1
    assert res.qa["top_topic"] == "冰块沉浮"
    assert (tmp_path / "scouted_topics.json").exists()


def test_capability_structure_clone_render(tmp_path):
    cap = caps.get("stickman.structure_clone")
    res = cap.render(
        {"new_topic": "沉没成本陷阱：为什么越努力越穷？", "target_duration": 60.0},
        tmp_path,
        duration=60.0,
        aspect="16:9",
        seed=1,
    )
    assert res.qa["stages_count"] == 5
    assert res.qa["facts_verified"] >= 2
    assert (tmp_path / "structure_script.json").exists()


def test_api_router_workflow(client):
    # 1. Topic scout endpoint
    csv_data = "channel_name,title,views,subscribers,monthly_uploads\n极客,冰块放油里沉底,600000,40000,2\n"
    r1 = client.post("/api/stickman/topic_scout", json={"source": csv_data})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["count"] == 1
    assert d1["topics"][0]["score"] > 20.0

    # 2. Structure clone endpoint
    r2 = client.post("/api/stickman/structure_clone", json={"new_topic": "为什么冰块放水里会浮放油里沉下去？"})
    assert r2.status_code == 200
    d2 = r2.json()
    script = d2["script"]
    assert len(script["stages"]) == 5

    # 3. Proposal create endpoint
    r3 = client.post("/api/stickman/proposal/create", json={"script_data": script, "aspect_ratio": "16:9"})
    assert r3.status_code == 200
    prop = r3.json()["proposal"]
    assert prop["status"] == "draft"

    # 4. Proposal approve endpoint
    r4 = client.post("/api/stickman/proposal/approve", json=prop)
    assert r4.status_code == 200
    approved_prop = r4.json()["proposal"]
    assert approved_prop["status"] == "approved"

    # 5. Credits summary endpoint
    r5 = client.get("/api/stickman/credits")
    assert r5.status_code == 200
    ledger_data = r5.json()["ledger"]
    assert ledger_data["monthly_remaining"] >= 0
    assert ledger_data["daily_remaining"] >= 0
