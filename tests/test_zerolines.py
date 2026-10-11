"""Zero-cost line engine: policy, pure algorithms, measured QA, fail-closed
workflow and Studio routing.  Media checks use real ffmpeg renders."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from hevi.layer4_legacy.zerolines.oprim_impl.specs import (
    LEGACY_ONLY_LINES,
    LINE_SPECS,
    ZERO_LINES,
    ZeroLineRequest,
    resolve_engine,
)
from hevi.layer4_legacy.zerolines.oskill_impl.audio_math import mouth_series, rms_from_pcm, synth_bgm
from hevi.layer4_legacy.zerolines.oskill_impl.captions import build_ass, kinetic_events, kinetic_words
from hevi.layer4_legacy.zerolines.oskill_impl.qa import frame_stats, judge
from hevi.layer4_legacy.zerolines.oskill_impl.shots import (
    camera_filter,
    director_shot_list,
    narration_shot_lengths,
    pick_windows,
    place_on_beats,
    xfade_graph,
)

FFMPEG = shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
HAVE_FFMPEG = Path(FFMPEG).exists()


# ---------------------------------------------------------------- policy
def test_eleven_zero_lines_and_two_legacy_only() -> None:
    from hevi.studio.production_catalog import CANONICAL_LINES

    assert len(ZERO_LINES) == 11 and set(ZERO_LINES) == set(LINE_SPECS)
    assert set(ZERO_LINES) | set(LEGACY_ONLY_LINES) == set(CANONICAL_LINES)
    assert not set(ZERO_LINES) & set(LEGACY_ONLY_LINES)


def test_engine_policy_slot_over_env_default_legacy() -> None:
    assert resolve_engine(line_id="explainer") == "legacy"
    assert resolve_engine(line_id="explainer", env_engine="zero") == "zero"
    assert resolve_engine(line_id="explainer", slot_engine="legacy", env_engine="zero") == "legacy"
    assert resolve_engine(line_id="explainer", slot_engine="ZERO") == "zero"
    for line in LEGACY_ONLY_LINES:
        assert resolve_engine(line_id=line, slot_engine="zero") == "legacy"
    with pytest.raises(ValueError):
        resolve_engine(line_id="explainer", slot_engine="gpu-magic")


def test_request_validation_is_strict() -> None:
    assert ZeroLineRequest("explainer", texts=("a",), queries=()).validate()
    assert ZeroLineRequest("explainer", texts=("a", "b"), queries=("q",)).validate()
    assert not ZeroLineRequest("explainer", texts=("a", "b"), queries=("q1", "q2")).validate()
    assert ZeroLineRequest("character_animation", texts=tuple("abcde")).validate()
    assert ZeroLineRequest("shorts_clip").validate()
    assert ZeroLineRequest("reference_adapt", texts=("a",), offsets=(1.0, 2.0), media_path="x").validate()
    assert ZeroLineRequest("documentary_montage", texts=("a",)).validate()
    assert ZeroLineRequest("talking_head", texts=("a",), lang="fr").validate()


# ---------------------------------------------------------------- pure algorithms
def test_bgm_and_mouth_series() -> None:
    y = synth_bgm(3.0, mood="bright", sr=8000)
    assert y.shape == (24000, 2) and y.dtype == np.int16 and np.abs(y).max() > 1000
    with pytest.raises(ValueError):
        synth_bgm(1.0, mood="nope")
    t = np.arange(16000) / 16000
    pcm = (np.sin(2 * np.pi * 220 * t) * (t > 0.5)).astype(np.float32)
    env = rms_from_pcm(pcm, fps=25)
    m = mouth_series(env)
    assert len(m) == 25 and set(np.unique(m)) <= {0, 0.25, 0.5, 0.75, 1.0}
    assert m[:10].max() == 0 and m[-5:].min() > 0


def test_captions_and_kinetic_plan() -> None:
    words = kinetic_words(["七十万年前，有人在这里点燃了第一堆火。", "周口店。"])
    assert words[0] == "七十万年前" and "周口店" in words and all(len(w) <= 8 for w in words)
    cues = [(0.0, 3.0, "七十万年前，有人在这里点燃了第一堆火。"), (3.4, 4.5, "周口店。")]
    ev = kinetic_events(words=words, cues=cues, total=6.0, width=1280, height=720)
    starts = [e[0] for e in ev]
    assert starts == sorted(starts) and starts[-1] >= 3.4
    doc = build_ass(width=1280, height=720, events=[(0, 1, "Cap", "第一行\n第二行"), (2, 1, "Cap", "bad")])
    assert doc.count("Dialogue:") == 1 and r"第一行\N第二行" in doc and "PlayResX: 1280" in doc


def test_shot_planning() -> None:
    assert "eval=frame" in camera_filter(move="push", d=3, width=1280, height=720)
    assert "crop=1280:720:x='(iw-1280)*t/3'" in camera_filter(move="pan_r", d=3, width=1280, height=720)
    with pytest.raises(ValueError):
        camera_filter(move="spin", d=3, width=10, height=10)
    graph, label = xfade_graph(durations=[3.0, 3.0, 3.0], xd=0.5)
    assert label == "[x2]" and "offset=2.500" in graph and "offset=5.000" in graph
    with pytest.raises(ValueError):
        xfade_graph(durations=[3.0, 0.4], xd=0.5)
    lengths = narration_shot_lengths([(0, 2, "a"), (2.35, 4, "b")], xd=0.5)
    assert lengths == pytest.approx([2.35, 1.65 + 0.35 + 0.5 + 1.2])
    plan = director_shot_list(texts=list("abcde"), queries=list("vwxyz"))
    assert [s["size"] for s in plan] == ["WIDE", "MEDIUM", "CLOSE", "MEDIUM", "WIDE"]
    assert director_shot_list(texts=["a"], queries=["q"], overrides=[{"camera": "pan_l"}])[0]["camera"] == "pan_l"
    segs = [{"start": i * 5.0, "end": i * 5.0 + 4.5} for i in range(20)]
    wins = pick_windows(segs, n=2)
    assert wins and all(18 <= segs[j]["end"] - segs[i]["start"] <= 32 for i, j in wins)
    assert place_on_beats([1.0, 1.5]) == [0.6, 4.8]
    with pytest.raises(ValueError):
        place_on_beats([6.0])


def test_qa_verdict_fails_static_and_blank_passes_motion() -> None:
    rng = np.random.default_rng(0)
    static = np.full((20, 54, 96), 128, np.uint8)
    moving = rng.integers(0, 255, (20, 54, 96), dtype=np.uint8)
    base = dict(duration_s=10, has_video=True, has_audio=True, mean_volume_db=-20, width=1280, height=720,
                expect_size=(1280, 720), min_motion=1.0, max_static_ratio=0.5, max_black_ratio=0.1,
                max_dark_ratio=0.5, min_volume_db=-45, expect_audio=True, min_duration_s=6)
    bad = judge(stats=frame_stats(static), **base)
    assert not bad["pass"] and any("static" in c for c in bad["failed_checks"])
    assert "not_blank_luma_std_ge_8" in bad["failed_checks"]
    good = judge(stats=frame_stats(moving), **base)
    assert good["pass"], good["failed_checks"]
    silent = judge(stats=frame_stats(moving), **{**base, "mean_volume_db": -91.0})
    assert not silent["pass"]
    wrong = judge(stats=frame_stats(moving), **{**base, "width": 640, "height": 360})
    assert "resolution_matches_spec" in wrong["failed_checks"]
    na = judge(stats=frame_stats(moving), **{**base, "max_dark_ratio": None})
    assert na["checks_not_applicable"] == ["dark_textcard_ratio"]


# ---------------------------------------------------------------- measured media QA (real ffmpeg)
def _render(path: Path, src: str, seconds: int = 8, audio: bool = True) -> Path:
    sep = ":" if "=" in src else "="
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}{sep}s=1280x720:d={seconds}:r=24"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=330:d={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg missing")
def test_measure_real_media(tmp_path: Path) -> None:
    from hevi.layer4_legacy.zerolines.omodul_impl._media import contact_sheet, measure

    spec = LINE_SPECS["explainer"]
    good = measure(_render(tmp_path / "moving.mp4", "testsrc2"), expect_size=(1280, 720), thresholds=spec.qa)
    assert good["pass"], good["failed_checks"]
    assert good["resolution"] == "1280x720" and len(good["sha256"]) == 64
    card = measure(_render(tmp_path / "card.mp4", "color=c=0x202020"), expect_size=(1280, 720), thresholds=spec.qa)
    assert not card["pass"] and any("static" in c for c in card["failed_checks"])
    mute = measure(_render(tmp_path / "mute.mp4", "testsrc2", audio=False), expect_size=(1280, 720), thresholds=spec.qa)
    assert "has_audio" in mute["failed_checks"]
    sheet = contact_sheet(tmp_path / "moving.mp4", tmp_path / "sheet.jpg")
    assert sheet.is_file() and sheet.stat().st_size > 5000


# ---------------------------------------------------------------- fail-closed workflow
def test_workflow_blocks_on_missing_inputs_and_never_raises(tmp_path: Path) -> None:
    from hevi.layer4_legacy.zerolines.omodul_impl.runtime import zero_line_workflow

    out = zero_line_workflow({}, {"line_id": "explainer", "texts": ["只有一句"]}, tmp_path)
    assert out["status"] == "blocked" and "queries" in out["reason"]
    rec = json.loads((tmp_path / "record.json").read_text())
    assert rec["status"] == "blocked" and rec["cost"]["usd"] == 0.0
    out = zero_line_workflow({}, {"line_id": "shorts_clip", "media_path": str(tmp_path / "nope.mp4")}, tmp_path / "b")
    assert out["status"] == "failed" and "not found" in out["reason"]
    assert zero_line_workflow({}, {"line_id": "localization_dub", "texts": ["x"]}, tmp_path / "c")["status"] == "blocked"


def test_workflow_quality_gate_failure_is_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A producer whose output is a static card must end ``failed`` (gate measured, not asserted)."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg missing")
    from hevi.layer4_legacy.zerolines.omodul_impl import _lines, runtime

    def static_card(req, d):
        return {"finals": [_render(d / "talking_head.mp4", "color=c=0x305070")], "provenance": []}

    monkeypatch.setitem(_lines.PRODUCERS, "talking_head", static_card)
    monkeypatch.setattr(runtime, "PRODUCERS", _lines.PRODUCERS)
    out = runtime.zero_line_workflow({}, {"line_id": "talking_head", "texts": ["你好"]}, tmp_path)
    assert out["status"] == "failed" and out["reason"].startswith("QUALITY_GATE_FAILED")
    assert (tmp_path / "contact_sheet.jpg").is_file()


# ---------------------------------------------------------------- Studio routing
def _order(line: str, **slots) -> dict:
    return {"target": line, "line_id": line, "slots": slots}


def test_studio_routes_by_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.studio import fulfill

    calls: list[str] = []

    async def fake_zero(order, output_dir):
        calls.append("zero")
        return {"status": "failed", "reason": "x"}

    monkeypatch.setattr(fulfill, "_render_zero_line", fake_zero)
    legacy_calls: list[str] = []

    async def fake_legacy(order, output_dir):
        legacy_calls.append("legacy")
        return {"status": "blocked"}

    # build the switch around a fake legacy renderer to observe routing
    routed = fulfill._engine_switch("kinetic_promo", fake_legacy)
    monkeypatch.delenv("HEVI_LINE_ENGINE", raising=False)
    asyncio.run(routed(_order("kinetic_promo"), tmp_path))
    asyncio.run(routed(_order("kinetic_promo", engine="zero"), tmp_path))
    monkeypatch.setenv("HEVI_LINE_ENGINE", "zero")
    asyncio.run(routed(_order("kinetic_promo"), tmp_path))
    asyncio.run(routed(_order("kinetic_promo", engine="legacy"), tmp_path))
    assert legacy_calls == ["legacy", "legacy"] and calls == ["zero", "zero"]
    host = fulfill._engine_switch("talking_head", fake_legacy)
    asyncio.run(host(_order("talking_head", engine="zero", renderer="talkcraft"), tmp_path))
    assert legacy_calls[-1] == "legacy" and calls == ["zero", "zero"]
    for line in ZERO_LINES:
        assert fulfill._RENDERERS[line].__name__.endswith("_or_zero")
    for line in LEGACY_ONLY_LINES:
        assert not fulfill._RENDERERS[line].__name__.endswith("_or_zero")


def test_zero_failure_never_completes_through_fulfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hevi.layer4_legacy.zerolines as zl
    from hevi.studio import fulfill

    monkeypatch.setattr(zl, "zero_line_workflow",
                        lambda c, i, o: {"status": "failed", "reason": "QUALITY_GATE_FAILED: x", "record_path": "r"})
    res = asyncio.run(fulfill.fulfill_order(_order("explainer", engine="zero", script_lines=["a"], queries=["b"]),
                                            execute=True, output_dir=tmp_path, render=True))
    assert res["status"] == "failed" and res["quality"]["passed"] is False
    res = asyncio.run(fulfill.fulfill_order(_order("explainer", engine="warp"), execute=True,
                                            output_dir=tmp_path, render=True))
    assert res["status"] == "blocked"


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg missing")
def test_zero_success_still_passes_canonical_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hevi.layer4_legacy.zerolines as zl
    from hevi.studio import fulfill

    # the canonical delivery gate resolves ffprobe from PATH
    monkeypatch.setenv("PATH", f"{Path(FFMPEG).parent}:{os.environ.get('PATH', '')}")
    video = _render(tmp_path / "explainer.mp4", "testsrc2", seconds=10)
    monkeypatch.setattr(zl, "zero_line_workflow", lambda c, i, o: {
        "status": "succeeded", "reason": "", "record_path": str(tmp_path / "record.json"),
        "finals": [str(video)], "qa": [{"pass": True}], "provenance": [{"source": "test render"}]})
    res = asyncio.run(fulfill.fulfill_order(_order("explainer", engine="zero"), execute=True,
                                            output_dir=tmp_path / "o", render=True))
    assert res["status"] == "completed", res
    assert res["render_runtime"] == "zero" and res["artifact_manifest"]["verified"] is True
    assert res["provenance"]["cost_usd"] == 0.0


def test_order_mapping_takes_inputs_only() -> None:
    from hevi.studio import fulfill

    m = fulfill._zero_input(_order("reference_adapt", script_lines=["一", {"text": "二"}], media_path="/x.mp4",
                                   offsets=[1, 2], zero_extras={"cta": "c"}, language="en"), "reference_adapt")
    assert m["texts"] == ["一", "二"] and m["media_path"] == "/x.mp4" and m["offsets"] == [1, 2]
    assert m["lang"] == "en" and m["extras"] == {"cta": "c"} and m["queries"] == []


# ---------------------------------------------------------------- qualification entry
def test_qualify_maps_host_lines_to_talkcraft_not_echomimic() -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "qualify_autonomous_production.py"
    spec = importlib.util.spec_from_file_location("qap", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    src = path.read_text()
    assert "EchoMimic" not in src and "ComfyUI" not in src
    for line in ("talking_head", "avatar_spokesperson"):
        assert "talkcraft" in mod._provider(line, "zero", "talkcraft")
        assert mod._slots(line, "zero", "talkcraft")["renderer"] == "talkcraft"
        assert mod._slots(line, "legacy", "talkcraft")["renderer"] == "talkcraft"
        assert mod._slots(line, "zero", "zero")["engine"] == "zero"
    briefs = json.loads(mod.ZERO_BRIEFS.read_text())["lines"]
    assert set(briefs) == set(ZERO_LINES)
    for line in ZERO_LINES:
        if line in ("talking_head", "avatar_spokesperson"):
            continue
        slots = mod._slots(line, "zero", "talkcraft")
        assert slots["engine"] == "zero" and mod._provider(line).startswith("zero")
        req = ZeroLineRequest(line, texts=tuple(slots.get("script_lines", ())), queries=tuple(slots.get("queries", ())),
                              media_path=slots.get("media_path", ""), offsets=tuple(slots.get("offsets", ())))
        assert not req.validate(), (line, req.validate())
    assert mod._slots("documentary_montage", "zero").get("engine") is None


@pytest.mark.slow
@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg missing")
def test_character_animation_real_render(tmp_path: Path) -> None:
    """Real CPU render (Piper + PIL puppet + ffmpeg) through the workflow."""
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import PIPER

    if not Path(PIPER).is_file():
        pytest.skip("piper not installed")
    from hevi.layer4_legacy.zerolines.omodul_impl.runtime import zero_line_workflow

    out = zero_line_workflow({}, {"line_id": "character_animation", "texts": ["他走向洞口。", "火把点亮了。"]}, tmp_path)
    assert out["status"] == "succeeded", out["reason"]
    qa = out["qa"][0]
    assert qa["resolution"] == "1280x720" and qa["duration"] >= 11.5 and qa["pass"]
    assert Path(qa["contact_sheet"]).is_file()


def test_acceptance_matrix_zero_gates_block_on_missing_or_tampered(tmp_path: Path) -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "acceptance_matrix.py"
    import sys

    spec = importlib.util.spec_from_file_location("acceptance_matrix_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclasses resolve their module via sys.modules
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    d = tmp_path / "explainer"
    d.mkdir()
    (d / "explainer.mp4").write_bytes(b"not the recorded bytes")
    (d / "record.json").write_text(json.dumps({
        "engine": "zero", "line_id": "explainer", "status": "succeeded", "cost": {"usd": 0.0, "paid_api": False},
        "qa": [{"path": str(d / "explainer.mp4"), "sha256": "0" * 64, "duration": 10.0, "pass": True}]}))
    gates = {g.key: g for g in mod.evaluate_zero_lines(tmp_path)}
    assert gates["Z1"].status == "BLOCKED" and "missing" in gates["Z1"].evidence
    assert gates["Z2"].status == "BLOCKED"


def test_veya_auto_mode_does_not_hijack_zero_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.studio import veya

    monkeypatch.delenv("HEVI_LINE_ENGINE", raising=False)
    assert veya._auto_mode("history_scene", "auto", {}) == "low_cost"
    assert veya._auto_mode("history_scene", "auto", {"engine": "zero"}) == "auto"
    assert veya._auto_mode("history_scene", "low_cost", {"engine": "zero"}) == "low_cost"
    monkeypatch.setenv("HEVI_LINE_ENGINE", "zero")
    assert veya._auto_mode("history_scene", "auto", {}) == "auto"
    assert veya._auto_mode("emotional_reading", "auto", {}) == "low_cost"  # no zero engine for it
