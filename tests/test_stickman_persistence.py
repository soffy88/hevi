"""G11 persistence tests: stickman ledger + proposals survive a restart.

"Restart" is simulated exactly as a new process would observe it: a
fresh CreditsLedger / fresh _load_proposals() read from the same files.
The live container-restart check is a rebuild-wave item (see report).
"""

from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.stickman.credits_ledger import CreditsLedger
from hevi.stickman import router as stickman_router


def test_global_ledger_is_file_backed():
    assert stickman_router._GLOBAL_LEDGER.ledger_file is not None


def test_ledger_survives_reload(tmp_path):
    ledger_file = tmp_path / "credits_ledger.json"
    first = CreditsLedger(ledger_file=ledger_file)
    first.record_consumption("prop_restart", 2)
    assert first.monthly_spent == 30
    # A new instance (as a restarted process would construct) reloads it.
    second = CreditsLedger(ledger_file=ledger_file)
    assert second.monthly_spent == 30
    assert second.get_summary()["monthly_remaining"] == 970
    assert len(second.transactions) == 1


def test_proposal_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKMAN_DATA_DIR", str(tmp_path))
    prop = {"proposal_id": "prop_persist", "status": "approved", "title": "t"}
    stickman_router._save_proposal(prop)
    assert stickman_router._load_proposals()["prop_persist"]["status"] == "approved"


def test_approved_proposal_readable_after_save(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKMAN_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    r2 = client.post(
        "/api/stickman/structure_clone",
        json={"new_topic": "为什么冰块放水里会浮放油里沉下去？"},
    )
    assert r2.status_code == 200
    script = r2.json()["script"]
    r3 = client.post(
        "/api/stickman/proposal/create",
        json={"script_data": script, "aspect_ratio": "16:9"},
    )
    assert r3.status_code == 200
    prop = r3.json()["proposal"]
    r4 = client.post("/api/stickman/proposal/approve", json=prop)
    assert r4.status_code == 200
    pid = r4.json()["proposal"]["proposal_id"]
    r5 = client.get(f"/api/stickman/proposals/{pid}")
    assert r5.status_code == 200
    assert r5.json()["proposal"]["status"] == "approved"
    # Fresh read from disk (what a restarted process sees).
    assert stickman_router._load_proposals()[pid]["status"] == "approved"
    r6 = client.get("/api/stickman/proposals/nonexistent")
    assert r6.status_code == 404
