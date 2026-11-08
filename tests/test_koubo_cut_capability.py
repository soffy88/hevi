"""Capability-level tests for koubo_cut.render."""

import pytest

import hevi.capabilities as caps
from hevi.capabilities import get
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.koubo_cut import register_koubo_cut_capabilities_once


def test_koubo_cut_registered():
    assert "koubo_cut.render" in caps.names()
    cap = get("koubo_cut.render")
    assert cap.line == "koubo_cut"


def test_register_idempotent():
    before = set(caps.names())
    assert register_koubo_cut_capabilities_once() == []
    assert set(caps.names()) == before


def test_topic_queries_follow_narration():
    from hevi.koubo_cut.pipeline import _topic_queries

    assert _topic_queries("AI 视频创作的未来已来，镜头和剪辑交给模型")[:2] == [
        "artificial intelligence technology",
        "video production camera",
    ]
    assert _topic_queries("城市清晨的第一杯咖啡，街角的风很轻")[:1] == ["coffee cup cafe"]
    assert _topic_queries("完全无关的一句话，没有任何可识别的主体") == []


def test_livliv_render_size_and_layout():
    from hevi.koubo_cut import pipeline

    assert pipeline.LIVLIV_RENDER_W >= 720
    x0, y0, x1, y1 = pipeline.LIVLIV_MAIN_BOX
    assert (x1 - x0, y1 - y0) == (pipeline.LIVLIV_RENDER_W, pipeline.LIVLIV_RENDER_H)


def test_run_koubo_cut_accepts_engine_params():
    import inspect
    from hevi.koubo_cut.pipeline import run_koubo_cut

    sig = inspect.signature(run_koubo_cut)
    assert sig.parameters["engine"].default == "wav2lip"
    assert sig.parameters["character_id"].default == "d03ft"


def test_wants_livliv_gating(monkeypatch):
    from hevi.studio.fulfill import _wants_livliv

    monkeypatch.setenv("LIVLIV_CHARACTERS_ENABLED", "true")
    assert _wants_livliv({"slots": {"avatar_engine": "livliv"}}) is True
    assert _wants_livliv({"slots": {"lip_sync_engine": "livliv"}}) is True
    assert _wants_livliv({"slots": {"avatar_engine": "wav2lip"}}) is False
    monkeypatch.setenv("LIVLIV_CHARACTERS_ENABLED", "false")
    assert _wants_livliv({"slots": {"avatar_engine": "livliv"}}) is False


@pytest.mark.asyncio
async def test_koubo_cut_render_runs_off_event_loop(monkeypatch, tmp_path):
    """LivLiv drives Playwright's sync API, which refuses to start inside a
    running asyncio loop; the renderer must be dispatched to a thread."""
    import threading
    from pathlib import Path

    import hevi.capabilities as caps_mod
    import hevi.studio.fulfill as f

    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    class _Result:
        def __init__(self, mp4: Path) -> None:
            self.mp4 = str(mp4)

    class _Cap:
        def render(self, params, out, **kwargs):
            seen["tid"] = threading.get_ident()
            p = Path(out) / "koubo_cut.mp4"
            p.write_bytes(b"fake")
            return _Result(p)

    class _Manifest:
        def primary_path(self):
            return None

        def model_dump(self, mode="json"):
            return {}

    async def _fake_verify(*args, **kwargs):
        return _Manifest(), {"passed": True, "verdict": "pass"}

    monkeypatch.setattr(caps_mod, "get", lambda name: _Cap())
    monkeypatch.setattr(f, "_verified_video_manifest", _fake_verify)

    res = await f._render_koubo_cut_line(
        {
            "line_id": "koubo_cut",
            "slots": {
                "script_text": "测试",
                "duration_s": 1,
                "avatar_engine": "livliv",
                "character_id": "d03ft",
            },
        },
        tmp_path,
    )
    assert res["status"] == "completed"
    assert res["avatar_engine"] == "livliv"
    assert seen["tid"] != loop_thread
