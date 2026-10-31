"""Contract tests for the creator-style-kit capabilities (CAPABILITY_CONTRACT.md).

The catalogue test reads the real kit checkout (skipped when absent); the
styled-render test is a real end-to-end render at low fps with bundled fonts.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.video import csk_styled_render as csk

KIT_HOME = Path(os.environ.get("HEVI_CSK_HOME", csk.CSK_DEFAULT_HOME))
kit_missing = not (KIT_HOME / "styles").exists()
needs_kit = pytest.mark.skipif(kit_missing, reason="creator-style-kit checkout absent")

BEATS = {
    "name": "csk-contract-test",
    "source": "contract test (示例数据)",
    "beats": [
        {"type": "chapter", "num": "01", "title": "风格测试", "sub": "Style Test"},
        {
            "type": "stat",
            "value": 87.6,
            "suffix": "%",
            "unit": "一次通过",
            "note": "示例数据 · <em>零样本</em>",
        },
    ],
}


def test_csk_capabilities_registered_and_listable() -> None:
    names = caps.names()
    assert "video.hyperframes_styles" in names
    assert "video.hyperframes_styled_render" in names
    listed = [c.name for c in caps.list(kind="video")]
    assert "video.hyperframes_styles" in listed
    assert "video.hyperframes_styled_render" in listed


def test_csk_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("video.hyperframes_styles", "video.hyperframes_styled_render"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected
        assert by_name[expected].get("params_schema"), expected


def test_styled_render_rejects_invalid_params() -> None:
    cap = caps.get("video.hyperframes_styled_render")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "not-a-style", "content": BEATS},
            Path("/tmp/csk-bad"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "warm-notebook"},  # missing required content
            Path("/tmp/csk-bad"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "warm-notebook", "content": BEATS, "bogus": 1},
            Path("/tmp/csk-bad"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )


@needs_kit
def test_styles_catalogue_render(tmp_path: Path) -> None:
    cap = caps.get("video.hyperframes_styles")
    result = cap.render_safe({}, tmp_path / "cat", duration=1.0, aspect="9:16", seed=1)
    catalogue = Path(result.qa["catalogue_json"])
    assert catalogue.is_file()
    assert result.qa["count"] == 18
    assert len(result.qa["style_ids"]) == 18
    payload = json.loads(catalogue.read_text(encoding="utf-8"))
    assert payload["count"] == 18
    ids = [s["id"] for s in payload["styles"]]
    assert "data-journal" in ids and "warm-notebook" in ids
    journal = next(s for s in payload["styles"] if s["id"] == "data-journal")
    assert journal["name_zh"] == "数据新闻"
    assert journal["best_for"] and journal["not"]

    catalogue.unlink()
    assert not catalogue.exists(), "contract: deleting the artifact must break verification"


def test_missing_kit_surfaces_as_capability_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HEVI_CSK_HOME", str(tmp_path / "no-such-kit"))
    cap = caps.get("video.hyperframes_styles")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "out", duration=1.0, aspect="9:16", seed=1)


@needs_kit
def test_styled_render_end_to_end(tmp_path: Path) -> None:
    cap = caps.get("video.hyperframes_styled_render")
    out_dir = tmp_path / "styled"
    result = cap.render_safe(
        {"style_id": "warm-notebook", "content": BEATS, "fps": 4},
        out_dir,
        duration=1.0,
        aspect="9:16",
        seed=5,
    )
    mp4 = Path(result.mp4)
    assert mp4.is_file() and mp4.stat().st_size > 20_000
    assert result.duration_s >= 2.0
    assert result.sha256
    assert result.qa["style_id"] == "warm-notebook"
    assert (out_dir / "project" / "compositions" / "csk-contract-test.html").is_file()

    # B2 sound pass: the delivered mp4 must carry an audio stream, and the
    # capability must report the cue mix + alignment measurement (not a
    # silent file presented as complete).
    assert result.qa["audio"]["status"] == "mixed"
    assert result.qa["audio"]["cue_count"] >= 1
    assert result.qa["audio"]["kit_sound_pass"] == "not_run"
    report_path = Path(result.qa["audio"]["report_json"])
    assert report_path.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(mp4)],
        check=True, capture_output=True, text=True,
    )
    assert set(probe.stdout.split()) == {"video", "audio"}

    # The seek renderer must actually animate: an early frame (title entering)
    # and a late frame (stat locked) must differ visibly.
    ffmpeg = "ffmpeg"
    frames = []
    for label, at in (("early", 1.0), ("late", max(1.2, result.duration_s - 0.5))):
        png = tmp_path / f"{label}.png"
        subprocess.run(
            [ffmpeg, "-y", "-ss", str(at), "-i", str(mp4), "-frames:v", "1", str(png)],
            check=True,
            capture_output=True,
        )
        frames.append(png)
    from PIL import Image, ImageChops

    diff = ImageChops.difference(
        Image.open(frames[0]).convert("RGB"), Image.open(frames[1]).convert("RGB")
    )
    assert diff.convert("L").getextrema()[1] > 10, "frames should differ (animation moved)"

    mp4.unlink()
    assert not mp4.exists(), "contract: deleting the artifact must break verification"


def test_styled_render_beats_schema_fail_names_field() -> None:
    """A list beat written with 'title' instead of 'head' fails naming the field.

    Runs before any kit/scaffold work, so it holds even when the kit is absent.
    """
    cap = caps.get("video.hyperframes_styled_render")
    bad = {
        "name": "bad-beats",
        "beats": [{"type": "list", "title": "要点", "items": [["a", 1]]}],
    }
    with pytest.raises(CapabilityError, match="beats schema fail"):
        cap.render_safe(
            {"style_id": "warm-notebook", "content": bad},
            Path("/tmp/csk-bad-beats"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    with pytest.raises(CapabilityError, match="head"):
        cap.render_safe(
            {"style_id": "warm-notebook", "content": bad},
            Path("/tmp/csk-bad-beats"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
