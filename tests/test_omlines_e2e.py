"""Integration tests for the zero-cost (``omlines_free_tier``) production lines.

These are *real* runs -- no mocks, no stubs.  Acceptance is measured:

* ffprobe: duration > 0 and an audio stream must exist;
* ``zl.qa()`` (frame statistics + volumedetect): every physical check must hold;
* input relevance: the supplied ``topic`` must appear in the burned-in subtitle
  source / record, and for photo-driven lines the supplied ``image_path`` must be
  provably on screen (pixel-level NCC against the crop the compositor recorded);
* a missing required input must produce ``failed`` with the missing key named --
  never a silent built-in sample.

To stay fast, the integration tests run a deliberately small test tier
(320x180, two short narration lines).  The full-size evidence run lives in
``scripts/run_omlines_e2e.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hevi.layer4_legacy.omlines.oprim_impl import zl  # noqa: E402
from hevi.layer4_legacy.omlines.omodul_impl.fallback import omlines_fallback_workflow  # noqa: E402
from hevi.studio.veya import produce  # noqa: E402
from scripts.qualify_autonomous_production import _slots  # noqa: E402
from scripts.run_omlines_e2e import _photo_on_screen, _presenter_rect, _topic_evidence  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestWarning")

TEST_RES = "320x180"
SHORT_SCRIPT = ["这是第一句测试解说。", "这是第二句测试解说。"]


def _assert_real_artifact(job, tmp_path: Path, topic: str) -> dict:
    """Assert the job produced a genuinely valid artifact and return its QA."""
    assert job.status in {"ready", "completed"}, f"job failed: {job.status} / {job.reason}"
    assert job.artifact, "no artifact produced"
    path = Path(job.artifact)
    assert path.is_file() and path.stat().st_size > 10_000, f"artifact missing/too small: {path}"

    qa = zl.qa(str(path))
    assert qa["duration"] > 0, "zero-length artifact"
    assert "audio" in qa["streams"], "artifact has no audio stream"
    assert qa["mean_volume_db"] is not None and qa["mean_volume_db"] > -45, "silent audio"
    failed = [k for k, v in qa["checks"].items() if not v]
    assert not failed, f"measured QA failed: {failed} ({qa['checks']})"

    assert topic in _topic_evidence(tmp_path), \
        f"input topic {topic!r} not reflected in subtitles or renderer record"
    return qa


@pytest.mark.asyncio
async def test_omlines_documentary_montage_uses_supplied_source(tmp_path):
    """documentary_montage must cut the *supplied* media and narrate the topic."""
    slots = {**_slots("documentary_montage", "a"), "resolution": TEST_RES,
             "script_lines": SHORT_SCRIPT}
    topic = slots["topic"]
    out = tmp_path / "documentary_montage"
    job = await produce(line_id="documentary_montage", slots=slots, output_dir=str(out),
                        execute=True, publish=False)
    _assert_real_artifact(job, out, topic)

    record = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert record["inputs"]["source"] == slots["source"], "line did not record the supplied source"
    prov = json.dumps(record["provenance"], ensure_ascii=False)
    assert Path(slots["source"]).name in prov, "provenance does not name the supplied source"


@pytest.mark.asyncio
async def test_omlines_localization_dub_uses_a_real_translator(tmp_path):
    """localization_dub must translate with a real free translator and dub in Chinese."""
    slots = {**_slots("localization_dub", "a"), "resolution": TEST_RES, "dub_seconds": 8.0}
    out = tmp_path / "localization_dub"
    job = await produce(line_id="localization_dub", slots=slots, output_dir=str(out),
                        execute=True, publish=False)
    _assert_real_artifact(job, out, slots["topic"])

    report = json.loads((out / "video_localization_report.json").read_text(encoding="utf-8"))
    assert report["translators"], "no translator recorded in provenance"
    assert report["translated_segments"], "nothing was translated"
    for seg in report["translated_segments"]:
        assert any("\u4e00" <= c <= "\u9fff" for c in seg), f"non-Chinese dub segment: {seg!r}"


@pytest.mark.asyncio
async def test_omlines_talking_head_renders_supplied_photo(tmp_path):
    """talking_head must place the caller's image_path on screen (pixel proof)."""
    slots = {**_slots("talking_head", "a"), "resolution": TEST_RES, "script_lines": SHORT_SCRIPT}
    out = tmp_path / "talking_head"
    job = await produce(line_id="talking_head", slots=slots, output_dir=str(out),
                        execute=True, publish=False)
    _assert_real_artifact(job, out, slots["topic"])

    rect = _presenter_rect(out, str(job.artifact))
    assert rect, "renderer published no presenter rectangle; photo cannot be verified"
    on_screen, score = _photo_on_screen(str(job.artifact), slots["image_path"], rect)
    assert on_screen, f"supplied photo not on screen (ncc={score})"

    # a different photo must NOT match -- guards against a vacuous check
    other = _slots("talking_head", "b")["image_path"]
    matched, _ = _photo_on_screen(str(job.artifact), other, rect)
    assert not matched, "photo check is not discriminative"


@pytest.mark.asyncio
async def test_omlines_two_topics_produce_different_output(tmp_path):
    """A slot-blind producer would emit identical bytes for both inputs."""
    outputs = []
    for variant in ("a", "b"):
        slots = {**_slots("explainer", variant), "resolution": TEST_RES,
                 "script_lines": [f"{_slots('explainer', variant)['topic']}，第一句。", "第二句测试解说。"]}
        out = tmp_path / f"explainer_{variant}"
        job = await produce(line_id="explainer", slots=slots, output_dir=str(out),
                            execute=True, publish=False)
        qa = _assert_real_artifact(job, out, slots["topic"])
        outputs.append(qa["sha256"])
    assert outputs[0] != outputs[1], "both topics produced byte-identical output"


@pytest.mark.parametrize("line,dropped", [
    ("documentary_montage", ("source", "media_path")),
    ("reference_adapt", ("source", "media_path")),
    ("shorts_clip", ("source", "media_path")),
    ("podcast_repurpose", ("source", "media_path")),
    ("localization_dub", ("source", "media_path")),
    ("talking_head", ("image_path",)),
    ("avatar_spokesperson", ("image_path",)),
    ("explainer", ("topic",)),
    ("cinematic", ("topic",)),
    ("kinetic_promo", ("topic",)),
    ("history_scene", ("topic",)),
    ("director_pipeline", ("topic",)),
    ("character_animation", ("topic",)),
])
def test_missing_required_input_fails_loudly(line, dropped):
    """A missing required slot must FAIL naming the slot -- never fall back to a demo."""
    drop = set(dropped) | {"variant"}
    slots = {k: v for k, v in _slots(line, "a").items() if k not in drop}
    result = omlines_fallback_workflow({}, {"line_id": line, **slots}, "/tmp/omlines-missing-input")
    assert result["status"] == "failed", f"{line} produced output without {dropped}: {result}"
    assert any(d in result["reason"] for d in dropped), \
        f"reason does not name the missing slot: {result['reason']}"
    assert not result.get("result_video_path"), "a video path was returned for a failed run"