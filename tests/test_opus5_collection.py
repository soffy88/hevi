"""Tests for the Opus 5.5 collection intake (2026-10-28).

Covers: opus prompt library search/get and the zhuyansen
metadata-only rule, lemo style catalogue + dedupe flags + code
prompt builder, code_render tiers/determinism/retry/assembly, and
karaoke_render execution (silent preview + WAV mux + negatives).
No network, no upstream code, no full-song renders: the longest
render here is 2 seconds.
"""

import json
import math
import struct
import wave
from pathlib import Path

import pytest
from PIL import Image

from hevi.capabilities import code_render, karaoke_render, lemo_styles
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.opus_prompt_library import (
    get_prompt,
    list_categories,
    list_tech_tags,
    search_prompts,
)


# --- opus prompt library -------------------------------------------------

def test_opus_search_by_category_and_tech():
    res = search_prompts(source="yihui", category="motion", tech="canvas", limit=5)
    assert res["total_in_index"] == 703
    assert res["matched"] > 0
    assert len(res["results"]) <= 5
    assert all("canvas" in [t.lower() for t in r["tech_tags"]] for r in res["results"])
    assert all(r["category"] == "motion" for r in res["results"])


def test_opus_search_alias_category():
    res = search_prompts(source="yihui", category="解说", limit=3)
    assert res["category"] == "explainer"
    assert res["matched"] > 0


def test_opus_search_unknown_category_and_tech_raise():
    with pytest.raises(CapabilityError):
        search_prompts(source="yihui", category="nope")
    with pytest.raises(CapabilityError):
        search_prompts(source="yihui", tech="nope-tech")
    with pytest.raises(CapabilityError):
        search_prompts(source="yihui", limit=0)


def test_opus_get_prompt_known_and_partial_flag():
    res = search_prompts(source="yihui", limit=1)
    slug = res["results"][0]["slug"]
    got = get_prompt(slug)
    assert got["slug"] == slug
    assert isinstance(got["prompt"], str) and got["prompt"]
    assert isinstance(got["prompt_partial"], bool)


def test_opus_zhuyansen_is_metadata_only():
    res = search_prompts(source="zhuyansen", category="motion", limit=3)
    assert res["total_in_index"] == 2220
    assert res["matched"] > 0
    assert all(r["prompt_text"] is None for r in res["results"])
    assert all("original_post_url" in r and r["original_post_url"] for r in res["results"])
    first_id = res["results"][0]["id"]
    with pytest.raises(CapabilityError):
        get_prompt(first_id)


def test_opus_categories_and_tech_tags():
    assert set(list_categories("yihui")) == {"motion", "3d", "explainer", "interactive"}
    assert "canvas" in list_tech_tags()
    assert "threejs" in list_tech_tags()


# --- lemo styles ----------------------------------------------------------

def test_lemo_catalogue_count_and_overlap_flags():
    if not Path("/data/soffy/projects/_refs/lemo-opuscar/styles").is_dir():
        pytest.skip("lemo-opuscar checkout not present")
    styles = lemo_styles.list_lemo_styles()
    assert len(styles) == 59
    by_slug = {s["slug"]: s for s in styles}
    for slug in ("blueprint", "dark-keynote", "ink-wash"):
        assert by_slug[slug]["hevi_overlap"] == "video.hyperframes_styles"
        assert by_slug[slug]["hevi_new"] is False
    assert sum(1 for s in styles if s["hevi_new"]) == 56
    assert all(s["essence"] for s in styles)


def test_lemo_get_and_code_prompt():
    if not Path("/data/soffy/projects/_refs/lemo-opuscar/styles").is_dir():
        pytest.skip("lemo-opuscar checkout not present")
    style = lemo_styles.get_lemo_style("art-deco")
    assert style["en"] == "Art Deco"
    built = lemo_styles.build_lemo_code_prompt("art-deco", "a night market", duration_sec=30)
    assert "a night market" in built["code_prompt"]
    assert "Midnight at the Starlight Hotel" not in built["code_prompt"]
    assert built["image_generation"] == "not_performed_here"
    with pytest.raises(CapabilityError):
        lemo_styles.get_lemo_style("no-such-style")


def test_lemo_registration():
    names = lemo_styles.register_lemo_styles_capabilities_once()
    assert names == [] or names == ["image.lemo_styles"]


# --- code_render ----------------------------------------------------------

def _flat_frame(color):
    def fn(t, i, w, h):
        return Image.new("RGB", (w, h), color)
    return fn


def test_code_render_tiers_and_unknown_tier():
    assert code_render.get_tier("uhd_2160p60")["width"] == 3840
    assert code_render.get_tier("uhd_2160p60")["fps"] == 60
    with pytest.raises(CapabilityError):
        code_render.get_tier("nope")


def test_code_render_deterministic_and_manifest(tmp_path):
    fn = _flat_frame((10, 20, 30))
    m1 = code_render.render_frames(fn, "draft_720p30", 0.2, tmp_path / "a")
    m2 = code_render.render_frames(fn, "draft_720p30", 0.2, tmp_path / "b")
    assert m1["frame_count"] == 6
    assert [f["sha256"] for f in m1["frames"]] == [f["sha256"] for f in m2["frames"]]
    assert m1["retried_frames"] == []


def test_code_render_wrong_size_and_failing_frame_raise(tmp_path):
    def wrong(t, i, w, h):
        return Image.new("RGB", (10, 10), (0, 0, 0))
    with pytest.raises(CapabilityError):
        code_render.render_frames(wrong, "draft_720p30", 0.1, tmp_path / "w")

    calls = {"n": 0}
    def failing(t, i, w, h):
        calls["n"] += 1
        raise RuntimeError("boom")
    with pytest.raises(CapabilityError):
        code_render.render_frames(failing, "draft_720p30", 0.1, tmp_path / "f", max_retries=2)
    assert calls["n"] == 3  # first try + 2 retries for frame 0


def test_code_render_assemble_no_audio(tmp_path):
    frames = code_render.render_frames(_flat_frame((200, 30, 30)), "draft_720p30", 0.2, tmp_path / "frames")
    out = code_render.assemble_mp4(tmp_path / "frames", 30, tmp_path / "out.mp4")
    assert Path(out["mp4"]).exists() and out["bytes"] > 0
    assert abs(out["duration_sec"] - 0.2) < 0.25
    with pytest.raises(CapabilityError):
        code_render.assemble_mp4(tmp_path / "empty", 30, tmp_path / "x.mp4")


# --- karaoke_render ---------------------------------------------------------

def _words():
    return [
        {"word": "hello", "start_sec": 0.0, "end_sec": 0.5},
        {"word": "bright", "start_sec": 0.5, "end_sec": 1.0},
        {"word": "world", "start_sec": 1.0, "end_sec": 1.5},
        {"word": "again", "start_sec": 1.5, "end_sec": 2.0},
    ]


def _sine_wav(path: Path, seconds: float = 1.0, rate: int = 22050):
    frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
                      for i in range(int(rate * seconds)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)


def test_karaoke_render_silent_preview(tmp_path):
    res = karaoke_render.build_karaoke_render(
        {"words": _words(), "source_duration_sec": 2.0},
        tier="draft_720p30", orientation="vertical", out_dir=tmp_path)
    assert res["audio_mode"] == "silent_preview"
    assert res["width"] == 720 and res["height"] == 1280
    assert res["word_count"] == 4 and res["frame_count"] == 60
    assert Path(res["mp4"]).exists() and res["mp4_bytes"] > 0
    assert abs(res["mp4_duration_sec"] - 2.0) < 0.25


def test_karaoke_render_wav_mux(tmp_path):
    wav = tmp_path / "tone.wav"
    _sine_wav(wav, seconds=1.0)
    res = karaoke_render.build_karaoke_render(
        {"words": [{"word": "la", "start_sec": 0.0, "end_sec": 0.5},
                   {"word": "la", "start_sec": 0.5, "end_sec": 1.0}],
         "source_duration_sec": 1.0},
        tier="draft_720p30", orientation="vertical",
        audio_path=wav, out_dir=tmp_path)
    assert res["audio_mode"] == "muxed"
    assert Path(res["mp4"]).exists()


def test_karaoke_render_negatives(tmp_path):
    bad = [{"word": "a", "start_sec": 0.0, "end_sec": 0.5},
           {"word": "b", "start_sec": 0.4, "end_sec": 0.9}]
    with pytest.raises(CapabilityError):
        karaoke_render.build_karaoke_render(
            {"words": bad, "source_duration_sec": 1.0},
            tier="draft_720p30", out_dir=tmp_path)
    with pytest.raises(CapabilityError):
        karaoke_render.build_karaoke_render(
            {"words": _words(), "source_duration_sec": 2.0},
            tier="nope", out_dir=tmp_path)
    with pytest.raises(CapabilityError):
        karaoke_render.build_karaoke_render(
            {"words": _words(), "source_duration_sec": 2.0},
            tier="draft_720p30", audio_path=tmp_path / "missing.wav",
            out_dir=tmp_path)


def test_karaoke_render_4k_frame_size(tmp_path):
    # Tier probe only: one 4K frame, not a full render.
    manifest = karaoke_render._render_frames_sized(
        lambda t, i, w, h: Image.new("RGB", (w, h), (0, 0, 0)),
        3840, 2160, 60, 1 / 60, tmp_path / "frames4k")
    assert manifest["frame_count"] == 1
    assert manifest["width"] == 3840 and manifest["height"] == 2160
