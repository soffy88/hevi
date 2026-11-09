"""Providers, credits and capability registration for ai_drama."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.ai_drama.credits import BudgetExceeded, CreditLedger
from hevi.ai_drama.providers import (
    KaggleGPUProvider,
    MiniMaxH3APIProvider,
    OfflineProvider,
    RunningHubH3Provider,
)
from hevi.ai_drama.providers.base import VideoRequest


def test_offline_provider_always_available_and_renders(tmp_path: Path) -> None:
    from PIL import Image

    img = tmp_path / "plate.png"
    Image.new("RGB", (108, 192), (30, 60, 90)).save(img)
    audio = tmp_path / "a.wav"
    import subprocess

    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo:d=1.2", "-ar", "48000", str(audio)], check=True)
    out = tmp_path / "clip.mp4"
    req = VideoRequest(prompt="p", output_path=out, duration_s=1.2, image=str(img), audio=str(audio))
    result = OfflineProvider().render(req)
    assert out.is_file() and out.stat().st_size > 0
    assert result.provider == "offline"


def test_no_keys_means_paid_providers_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RUNNINGHUB_API_KEY", "RUNNINGHUB_WORKFLOW_ID", "MINIMAX_API_KEY",
                "KAGGLE_USERNAME", "KAGGLE_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert RunningHubH3Provider().available()[0] is False
    assert MiniMaxH3APIProvider().available()[0] is False
    assert KaggleGPUProvider().available()[0] in (False, True)  # True only if a kaggle.json exists
    if not (Path.home() / ".kaggle" / "kaggle.json").is_file():
        assert KaggleGPUProvider().available()[0] is False


def test_budget_cap_refuses_before_spend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_DRAMA_PRICES", json.dumps({"minimax_h3_api": 1.0}))
    ledger = CreditLedger(tmp_path / "ledger.jsonl", episode_id="e1", cap_cny=2.0)
    ledger.reserve("minimax_h3_api", 1.0, ref="s1")
    ledger.settle("minimax_h3_api", 1.0, ref="s1")
    assert ledger.spent() == pytest.approx(1.0)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("minimax_h3_api", 5.0, ref="s2")


def test_offline_is_free(tmp_path: Path) -> None:
    ledger = CreditLedger(tmp_path / "ledger.jsonl", episode_id="e2", cap_cny=30.0)
    price = ledger.reserve("offline", 60.0)
    assert price["estimated_cny"] == 0.0
    ledger.settle("offline", 60.0)
    assert ledger.spent() == 0.0


def test_capabilities_registered() -> None:
    import hevi.capabilities as caps

    names = set(caps.names())
    for name in ("drama.ai_script", "drama.ai_storyboard", "drama.ai_assets", "drama.ai_voice",
                 "drama.ai_segments", "drama.ai_edit", "drama.ai_episode", "drama.game_pov_ui",
                 "drama.game_pov_dialogue_box", "drama.provider_status"):
        assert name in names
    assert caps.get("drama.provider_status").line == "ai_drama"


def test_runninghub_requires_workflow_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNNINGHUB_API_KEY", "k")
    monkeypatch.delenv("RUNNINGHUB_WORKFLOW_ID", raising=False)
    ok, reason = RunningHubH3Provider().available()
    assert ok is False and "WORKFLOW_ID" in reason


def test_minimax_refuses_local_media_without_public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    monkeypatch.delenv("MINIMAX_FILE_BASE", raising=False)
    provider = MiniMaxH3APIProvider()
    req = VideoRequest(prompt="x", output_path=Path("/tmp/x.mp4"), duration_s=5,
                       mode="reference", reference_images=["/tmp/a.png"])
    from hevi.ai_drama.providers.minimax import MiniMaxConfigError

    with pytest.raises(MiniMaxConfigError):
        provider._content(req)


def test_real_person_reference_is_rejected_without_declaration(tmp_path: Path) -> None:
    from hevi.ai_drama.compliance import ReferenceRejected, assert_reference_allowed

    with pytest.raises(ReferenceRejected):
        assert_reference_allowed(tmp_path / "star.jpg", None)
    assert_reference_allowed(tmp_path / "gen.png", {"synthetic": True, "no_real_person": True})


def test_output_requires_ai_label() -> None:
    from hevi.ai_drama.compliance import ReferenceRejected, output_label

    with pytest.raises(ReferenceRejected):
        output_label({"ai_label": False})
    assert output_label({"ai_label": True, "ai_label_text": "AI 生成"}) == "AI 生成"


def test_voice_runs_before_storyboard(tmp_path) -> None:
    from hevi.ai_drama.pipeline import Pipeline

    p = Pipeline(tmp_path / "ep", episode_id="voice-first")
    stages = ["script", "voice", "storyboard", "assets", "segments", "edit", "delivery"]
    p.run({"theme": "第一次约会", "style": "live_action"})
    graph = __import__("json").loads((tmp_path / "ep" / "canvas_graph.json").read_text())
    assert [n["label"] for n in graph["nodes"]] == stages
