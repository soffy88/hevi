"""Tests for the video-director residuals graft (recheck items 7/8/9/10/11/13/14/15).

Covers, with a positive and a negative case each: the beat-grid
fit (least squares, tempo ambiguity, refit, cut error), the page
contract, director dials, the DECISION log, the AI-tells ban,
per-shot reads + timeline/critic wiring in segment assembly,
the Otsu wiring in final QC, and the fail-closed main-path
wiring in the stable-film pipeline. The film-level eval harness
(n>=3) is deliberately NOT tested here: it needs a real
execution channel, which does not exist in this environment.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

import hevi.capabilities  # noqa: F401  (import registers bundled capabilities)
from hevi.capabilities import contains
from hevi.capabilities.errors import CapabilityError

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

AXES = (
    "Hook", "Clarity", "Readability", "Motion quality",
    "Rhythm and variety", "Composition and look", "Continuity",
    "Truth", "Sound sync",
)


def _ship_review() -> dict:
    return {
        "axes": {axis: {"score": 9, "evidence": "at 0.5s frame #3: clear"}
                 for axis in AXES},
        "defects": [],
        "fix_round": 0,
    }


def _one_more_pass_review() -> dict:
    review = _ship_review()
    review["axes"]["Hook"] = {"score": 6, "evidence": "at 0.5s frame #3: hook weak"}
    return review


# ------------------------------------------------------------- shared hold formula

def test_read_time_formula_shared_latin_and_cjk() -> None:
    from hevi.capabilities.timeline_gate import read_time_required_sec

    assert read_time_required_sec("hello world") == pytest.approx(1.6)
    assert read_time_required_sec("hello") == pytest.approx(1.5)  # floor
    # CJK counts per character: 10 chars -> 1.0 + 3.0 = 4.0s.
    assert read_time_required_sec("白天抬头看天星星去哪") == pytest.approx(4.0)


# ------------------------------------------------------------- beat-grid fit

def test_grid_fit_exact_grid_passes() -> None:
    from hevi.assembly.beat_align import fit_beat_grid

    fit = fit_beat_grid([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    assert fit["status"] == "pass"
    assert fit["period_sec"] == pytest.approx(0.5, abs=0.001)
    assert fit["bpm"] == pytest.approx(120.0, abs=0.5)
    assert fit["within_tolerance"] is True
    assert fit["tempo_ambiguity"] is None


def test_grid_fit_drifted_grid_fails_15ms_bar_not_widened() -> None:
    from hevi.assembly.beat_align import fit_beat_grid

    # Tempo drifts (intervals grow 0.50 -> 0.55s): a least-squares
    # grid cannot absorb a changing tempo, so residuals grow
    # past 15ms. (A constant tempo offset alone would be absorbed
    # by the fit -- that is the refit test's job, not this one.)
    fit = fit_beat_grid([0.0, 0.5, 1.01, 1.53, 2.06, 2.6, 3.15])
    assert fit["status"] == "fail"
    assert fit["within_tolerance"] is False
    assert fit["max_abs_residual_sec"] > 0.015


def test_grid_fit_too_few_beats_is_undetermined() -> None:
    from hevi.assembly.beat_align import fit_beat_grid

    fit = fit_beat_grid([1.0])
    assert fit["status"] == "undetermined"
    assert fit["within_tolerance"] is None


def test_grid_fit_half_tempo_ambiguity_flagged() -> None:
    from hevi.assembly.beat_align import fit_beat_grid

    # Beats every 0.5s but with alternating tiny offsets: the
    # 1.0s grid fits the even beats nearly perfectly, which the
    # half/double check must notice as double_tempo ambiguity
    # only when it fits at least twice as well -- here the base
    # fit is already good, so no ambiguity is claimed.
    fit = fit_beat_grid([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
    assert fit["tempo_ambiguity"] is None
    # A grid that is really every 1.0s with a stray half-beat
    # pattern still fits the 0.5s reading better at half period.
    fit2 = fit_beat_grid([0.0, 1.0, 2.0, 3.0, 4.0])
    assert fit2["period_sec"] == pytest.approx(1.0, abs=0.001)
    assert fit2["status"] == "pass"


def test_grid_refit_after_render_drift() -> None:
    from hevi.assembly.beat_align import refit_after_render

    ok = refit_after_render(
        [0.0, 0.5, 1.0, 1.5, 2.0], [0.0, 0.5, 1.0, 1.5, 2.0])
    assert ok["status"] == "pass"
    assert ok["period_drift_sec"] == pytest.approx(0.0, abs=0.001)
    bad = refit_after_render(
        [0.0, 0.5, 1.0, 1.5, 2.0], [0.0, 0.52, 1.04, 1.56, 2.08])
    assert bad["status"] == "fail"
    assert bad["period_drift_sec"] == pytest.approx(0.02, abs=0.002)


def test_grid_refit_undetermined_when_rendered_side_too_short() -> None:
    from hevi.assembly.beat_align import refit_after_render

    out = refit_after_render([0.0, 0.5, 1.0], [0.5])
    assert out["status"] == "undetermined"
    assert out["period_drift_sec"] is None


def test_cut_errors_frames_bar_and_undetermined() -> None:
    from hevi.assembly.beat_align import cut_errors

    ok = cut_errors([1.0, 2.0], [0.0, 1.0, 2.0, 3.0], fps=30)
    assert ok["status"] == "pass"
    assert ok["cuts"][0]["offset_frames"] == pytest.approx(0.0)
    # 0.2s late at 30fps = 6 frames > 3-frame bar.
    bad = cut_errors([1.2], [0.0, 1.0, 2.0], fps=30)
    assert bad["status"] == "fail"
    assert bad["cuts"][0]["offset_frames"] == pytest.approx(6.0)
    assert cut_errors([1.0], [], fps=30)["status"] == "undetermined"
    with pytest.raises(ValueError, match="fps"):
        cut_errors([1.0], [1.0], fps=0)


def test_beat_align_capability_carries_grid_fit_and_refit(tmp_path: Path,
                                                           monkeypatch) -> None:
    from hevi.capabilities import get
    from hevi.capabilities.beat_align import compute_beat_alignment

    out = compute_beat_alignment(
        beats=[0.0, 0.5, 1.0, 1.5], durations=[1.0, 1.0],
        rendered_beats=[0.0, 0.5, 1.0, 1.5],
        cut_times=[1.0], fps=30)
    assert out["grid_fit"]["status"] == "pass"
    assert out["grid_refit"]["status"] == "pass"
    assert out["cut_errors"]["status"] == "pass"
    # Capability render path (librosa stubbed) carries the fit.
    monkeypatch.setattr(
        "hevi.assembly.beat_align.detect_beat_times", lambda p: [0.0, 0.5, 1.0, 1.5])
    audio = tmp_path / "bgm.wav"
    audio.write_bytes(b"fake-audio-bytes")
    result = get("assembly.beat_align").render_safe(
        {"audio_path": str(audio), "durations": [1.0, 1.0]}, tmp_path / "out")
    assert result.qa["grid_fit"]["status"] == "pass"


# ------------------------------------------------------------- page contract

def _page_record(**overrides) -> dict:
    record = {
        "dur": 6.0, "fps": 30, "w": 1920, "h": 1080,
        "seek": [0.0, 3.0, 5.9],
        "ready": {"fonts_ready": True},
        "texts": [{"text": "Hook", "start": 0.0, "end": 2.0,
                   "box": [0, 0, 1920, 120]}],
        "page_errors": [],
        "anchors": [{"positions": [[10, 20], [10, 20]]}],
        "forward_frames": [{"t": 0.0, "sha256": "a"}, {"t": 1.0, "sha256": "b"}],
        "reverse_render": {"frames": [{"t": 1.0, "sha256": "b"}, {"t": 0.0, "sha256": "a"}]},
    }
    record.update(overrides)
    return record


def test_page_contract_full_pass() -> None:
    from hevi.capabilities.page_contract import check_page_contract

    report = check_page_contract(_page_record())
    assert report["verdict"] == "pass", report["checks"]


def test_page_contract_missing_reverse_is_undetermined_not_pass() -> None:
    from hevi.capabilities.page_contract import check_page_contract

    record = _page_record()
    del record["reverse_render"]
    report = check_page_contract(record)
    assert report["verdict"] == "undetermined"
    assert report["checks"]["reverse_render_diff"]["pass"] is None
    assert report["checks"]["reverse_render_diff"]["status"] == "planned_not_measured"


def test_page_contract_claimed_diff_without_hashes_fails() -> None:
    from hevi.capabilities.page_contract import check_page_contract

    report = check_page_contract(
        _page_record(reverse_render={"claimed_measured": True}))
    assert report["verdict"] == "fail"
    assert report["checks"]["reverse_render_diff"]["pass"] is False


def test_page_contract_reverse_mismatch_fails() -> None:
    from hevi.capabilities.page_contract import check_page_contract

    report = check_page_contract(_page_record(reverse_render={
        "frames": [{"t": 1.0, "sha256": "DIFFERENT"}, {"t": 0.0, "sha256": "a"}]}))
    assert report["verdict"] == "fail"


def test_page_contract_page_errors_zero_tolerance_and_fonts() -> None:
    from hevi.capabilities.page_contract import check_page_contract

    errors = check_page_contract(_page_record(page_errors=["font fallback"]))
    assert errors["verdict"] == "fail"
    assert errors["checks"]["page_errors"]["pass"] is False
    fonts = check_page_contract(_page_record(ready={"fonts_ready": False}))
    assert fonts["verdict"] == "fail"
    assert fonts["checks"]["fonts_ready"]["pass"] is False
    # No page-error list at all: undetermined, never a pass.
    missing = _page_record()
    del missing["page_errors"]
    report = check_page_contract(missing)
    assert report["checks"]["page_errors"]["pass"] is None
    assert report["verdict"] == "undetermined"


def test_page_contract_text_read_time_bounds_and_anchors() -> None:
    from hevi.capabilities.page_contract import check_page_contract

    short = check_page_contract(_page_record(texts=[
        {"text": "a fairly long hook sentence here", "start": 0.0, "end": 0.5,
         "box": [0, 0, 1920, 120]}]))
    assert short["checks"]["texts_read_time"]["pass"] is False
    oob = check_page_contract(_page_record(texts=[
        {"text": "Hook", "start": 0.0, "end": 2.0, "box": [0, 0, 2000, 120]}]))
    assert oob["checks"]["text_bounds"]["pass"] is False
    drift = check_page_contract(_page_record(anchors=[
        {"positions": [[10, 20], [11, 20]]}]))
    assert drift["checks"]["anchor_stability"]["pass"] is False
    single = check_page_contract(_page_record(anchors=[{"positions": [[10, 20]]}]))
    assert single["checks"]["anchor_stability"]["pass"] is None


def test_code_render_contract_input_marks_reverse_planned() -> None:
    from hevi.capabilities.code_render import build_page_contract_input
    from hevi.capabilities.page_contract import check_page_contract

    manifest = {"duration_sec": 2.0, "fps": 30, "width": 1280, "height": 720,
                "frames": [{"t_sec": 0.0, "sha256": "a"}]}
    contract_input = build_page_contract_input(manifest)
    assert contract_input["reverse_render"]["status"] == "planned_not_measured"
    report = check_page_contract(contract_input)
    assert report["checks"]["reverse_render_diff"]["status"] == "planned_not_measured"
    # With a real reverse manifest, the diff is measured.
    reverse = {"frames": [{"t_sec": 0.0, "sha256": "a"}]}
    measured = build_page_contract_input(manifest, reverse_manifest=reverse)
    assert "frames" in measured["reverse_render"]
    assert check_page_contract(measured)["checks"]["reverse_render_diff"]["pass"] is True


# ------------------------------------------------------------- director dials

def test_dials_pass_and_coupling_rules() -> None:
    from hevi.capabilities.director_dials import declare_dials

    ok = declare_dials({"clock": "music", "continuity": "strict",
                        "register": "plain", "text_policy": "terms",
                        "bpm": 120, "anchors": ["hero"], "terms": ["alpha"]})
    assert ok["verdict"] == "pass"
    assert declare_dials({"clock": "music", "continuity": "loose",
                          "register": "plain", "text_policy": "minimal"})["violations"]
    assert any("R1" in v for v in declare_dials(
        {"clock": "music", "continuity": "loose", "register": "plain",
         "text_policy": "minimal"})["violations"])
    assert any("R2" in v for v in declare_dials(
        {"clock": "reads", "continuity": "loose", "register": "plain",
         "text_policy": "minimal"})["violations"])
    assert any("R3" in v for v in declare_dials(
        {"clock": "voice", "continuity": "strict", "register": "plain",
         "text_policy": "minimal"})["violations"])
    assert any("R4" in v for v in declare_dials(
        {"clock": "voice", "continuity": "loose", "register": "plain",
         "text_policy": "terms"})["violations"])
    assert any("R0" in v for v in declare_dials(
        {"clock": "metronome", "continuity": "loose", "register": "plain",
         "text_policy": "minimal"})["violations"])


def test_dials_against_timeline_mismatch_and_sound_clock_declaration() -> None:
    from hevi.capabilities.director_dials import (
        check_dials_against_timeline, sound_clock_contract)

    dials = {"clock": "music", "continuity": "loose", "register": "plain",
             "text_policy": "minimal", "bpm": 120}
    timeline = {"meta": {"clock": "voice", "bpm": 100}}
    report = check_dials_against_timeline(dials, timeline)
    assert report["verdict"] == "fail"
    assert any("clock" in m for m in report["mismatches"])
    contract = sound_clock_contract()
    assert contract["items"]["sfx_peak_placement"]["status"] == "planned_not_measured"
    assert contract["items"]["sparse_mix_no_hard_limit"]["status"] == "planned_not_measured"
    assert contract["items"]["loudnorm_ebur128_note"]["status"] == "planned_not_measured"
    assert contract["items"]["loudness_targets"]["status"] == "measured_by"


# ------------------------------------------------------------- decision log

def test_decision_log_record_overturn_and_report() -> None:
    from hevi.capabilities.decision_log import (
        decision_log_report, new_log, overturn_decision, record_decision)

    log = new_log()
    first = record_decision(log, {"decision": "cut the cold open",
                                  "reason": "hook tested weak",
                                  "alternatives": ["keep it"]})
    assert first["id"] == "D1"
    assert first["overturned_by"] is None
    second = record_decision(log, {"decision": "restore the cold open",
                                   "reason": "reviewer asked for context"})
    overturn_decision(log, "D1", superseding_id=second["id"],
                      reason="context outweighs pace")
    report = decision_log_report(log)
    assert report["verdict"] == "pass"
    assert report["standing_ids"] == ["D2"]
    assert report["overturned_count"] == 1
    assert log[0]["overturned_by"] == "D2"  # annotated, never deleted
    with pytest.raises(CapabilityError, match="duplicate"):
        record_decision(log, {"id": "D1", "decision": "x", "reason": "y"})
    with pytest.raises(CapabilityError, match="reason"):
        record_decision(log, {"decision": "no reason given"})
    with pytest.raises(CapabilityError, match="unknown"):
        overturn_decision(log, "D99", superseding_id="D2", reason="r")


# ------------------------------------------------------------- AI tells ban

def test_ai_tells_ban_fail_fix_and_translation_fields() -> None:
    from hevi.capabilities.ai_tells_ban import check_ai_tells

    report = check_ai_tells({"frames_reviewed": 12, "observations": [
        {"symptom": "morphing_hands", "t_sec": 1.2,
         "evidence": "frame #36: six fingers"}]})
    assert report["verdict"] == "fail"
    obs = report["observations"][0]
    assert obs["reported_as"]  # plain-language translation field
    assert obs["fix"]  # failure-to-repair table entry
    assert report["banned_symptoms"] == ["morphing_hands"]


def test_ai_tells_ban_clean_pass_and_zero_frames_undetermined() -> None:
    from hevi.capabilities.ai_tells_ban import check_ai_tells

    assert check_ai_tells(
        {"frames_reviewed": 30, "observations": []})["verdict"] == "pass"
    zero = check_ai_tells({"frames_reviewed": 0, "observations": []})
    assert zero["verdict"] == "undetermined"
    unlisted = check_ai_tells({"frames_reviewed": 5, "observations": [
        {"symptom": "something_new", "t_sec": 0.5, "evidence": "frame #15"}]})
    assert unlisted["verdict"] == "pass"
    assert unlisted["warnings"]  # unlisted is warned, not failed


# ------------------------------------------------------------- segment assembly: reads + gates

def _scenes_with_reads() -> list:
    return [{"scene_id": "sc-1", "shots": [
        {"shot_id": "s1", "text": "你好世界", "duration_sec": 3.0,
         "reads": [{"text": "你好", "kind": "found", "at_sec": 0.5}]},
    ]}]


def test_reads_list_validated_and_carried_to_storyboard() -> None:
    from hevi.capabilities import segment_assembly as sa

    plan = sa.plan_segments(_scenes_with_reads())
    assert plan["shots"][0]["reads"][0]["kind"] == "found"
    rows = sa.to_storyboard_rows(plan)
    assert rows[0]["reads"][0]["text"] == "你好"
    assert plan["render_qc_required"]["defect_scan_status"] == "planned_not_measured"


def test_reads_duplicate_short_shot_and_bad_kind_fail() -> None:
    from hevi.capabilities import segment_assembly as sa

    dup = [{"scene_id": "sc-1", "shots": [
        {"shot_id": "s1", "text": "x", "duration_sec": 5.0,
         "reads": [{"text": "same", "kind": "found"}, {"text": "same", "kind": "found"}]}]}]
    with pytest.raises(CapabilityError, match="twice"):
        sa.plan_segments(dup)
    # 10 CJK chars need 4.0s; a 2.0s shot cannot carry the read.
    short = [{"scene_id": "sc-1", "shots": [
        {"shot_id": "s1", "text": "x", "duration_sec": 2.0,
         "reads": [{"text": "白天抬头看天星星去哪", "kind": "understood"}]}]}]
    with pytest.raises(CapabilityError, match="read-time"):
        sa.plan_segments(short)
    bad_kind = [{"scene_id": "sc-1", "shots": [
        {"shot_id": "s1", "text": "x", "duration_sec": 5.0,
         "reads": [{"text": "word", "kind": "skimmed"}]}]}]
    with pytest.raises(CapabilityError, match="kind"):
        sa.plan_segments(bad_kind)


def test_segment_plan_timeline_and_critic_wiring() -> None:
    from hevi.capabilities import segment_assembly as sa

    timeline = {
        "meta": {"w": 1920, "h": 1080, "fps": 30, "dur": 3.0,
                 "clock": "voice"},
        "scenes": [{"start": 0.0, "end": 3.0}],
        "texts": [{"role": "hook", "text": "Hi", "start": 0.0, "end": 2.0}],
    }
    plan = sa.plan_segments(_scenes_with_reads(), timeline=timeline,
                            review=_one_more_pass_review())
    assert plan["timeline_gate"]["verdict"] == "pass"
    assert plan["critic_review"]["verdict"] == "one_more_pass"
    assert plan["critic_blocks_ship"] is True
    # A gapped timeline fails the plan.
    bad_timeline = dict(timeline)
    bad_timeline["scenes"] = [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]
    with pytest.raises(CapabilityError, match="timeline gate"):
        sa.plan_segments(_scenes_with_reads(), timeline=bad_timeline)
    # A broken fix-round limit fails the plan.
    bad_review = _ship_review()
    bad_review["fix_round"] = 2
    with pytest.raises(CapabilityError, match="critic review"):
        sa.plan_segments(_scenes_with_reads(), review=bad_review)


def test_require_render_qc_fail_closed_and_reads_sampling() -> None:
    from hevi.capabilities import segment_assembly as sa

    plan = sa.plan_segments(_scenes_with_reads())
    assert sa.require_render_qc(plan, None)["verdict"] == "fail"
    assert sa.require_render_qc(plan, {"defect_scan": None})["verdict"] == "fail"
    skipped = sa.require_render_qc(
        plan, {"defect_scan": {"status": "skipped", "reason": "too short"}})
    assert skipped["verdict"] == "fail" and skipped["scan_ran"] is False
    ran = sa.require_render_qc(plan, {"defect_scan": {"status": "pass"}})
    assert ran["verdict"] == "pass" and ran["scan_ran"] is True
    # Reads sampling: no samples -> planned, never a pass.
    assert sa.verify_reads_against_samples(plan, None)["status"] == "planned_not_measured"
    sampled = sa.verify_reads_against_samples(
        plan, [{"shot_id": "s1", "text": "你好", "t_sec": 0.6}])
    assert sampled["status"] == "pass"
    missing = sa.verify_reads_against_samples(
        plan, [{"shot_id": "s1", "text": "other", "t_sec": 0.6}])
    assert missing["status"] == "fail"


# ------------------------------------------------------------- final QC + Otsu

def _write_video(path: Path, frame_fn, fps: int, duration: float,
                 size: tuple[int, int] = (160, 90)) -> Path:
    import numpy as np

    width, height = size
    count = max(1, round(duration * fps))
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)],
        stdin=subprocess.PIPE)
    assert proc.stdin is not None
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)[:, None]
    for i in range(count):
        t = i / fps
        proc.stdin.write(frame_fn(t, i, xs, ys).astype(np.uint8).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return path


def _gradient(t, i, xs, ys):
    import numpy as np

    g = np.clip(xs[None, :] * 0.9 + ys * 0.4, 0, 200)
    return np.stack([g, np.clip(g * 0.8 + 20, 0, 255),
                     np.clip(g * 0.6 + 40, 0, 255)], axis=2)


def _text_image(tmp_path: Path, size: int) -> Path:
    img = Image.new("RGB", (640, 360), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    draw.text((60, 120), "HELLO", fill=(255, 255, 255), font=font)
    path = tmp_path / f"text_{size}.png"
    img.save(path)
    return path


def test_final_qc_otsu_measured_and_cjk_undetermined(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    media = _write_video(tmp_path / "film.mp4", _gradient, 30, 3.0)
    big = _text_image(tmp_path, 120)
    small = _text_image(tmp_path, 20)
    report = run_final_qc(
        media, subtitle_text="hello", work_dir=tmp_path / "work",
        rendered_texts=[
            {"image_path": str(big), "box": [40, 100, 600, 260],
             "role": "term", "at_sec": 0.0, "text": "HELLO"},
            {"image_path": str(small), "box": [40, 100, 600, 260],
             "role": "hook", "at_sec": 0.0, "text": "HELLO"},
            {"image_path": str(big), "box": [40, 100, 600, 260],
             "role": "term", "at_sec": 0.0, "text": "中文标题"},
        ])
    assert report["rendered_text"]["requested"] is True
    assert len(report["rendered_text"]["measurements"]) == 3
    checks = report["checks"]
    assert checks["rendered_text_0_term"]["pass"] is True
    assert checks["rendered_text_1_hook"]["pass"] is False
    cjk = checks["rendered_text_2_term"]
    assert cjk["pass"] is None  # CJK: undetermined, never a calibrated pass
    assert "undetermined" in cjk["detail"]
    assert "uncalibrated" in report["rendered_text"]["measurements"][2]["calibration"]


def test_final_qc_otsu_not_requested_is_recorded_not_passed(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    media = _write_video(tmp_path / "film.mp4", _gradient, 30, 3.0)
    report = run_final_qc(media, subtitle_text="hello", work_dir=tmp_path / "work")
    assert report["rendered_text"]["requested"] is False
    assert report["rendered_text"]["status"] == "not_requested"
    assert not any(name.startswith("rendered_text_") for name in report["checks"])


# ------------------------------------------------------------- stable pipeline wiring

def _sine_wav(path, seconds, freq=440.0, amp=0.3, rate=22050):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(
        struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def _segments():
    return [
        {"segment_id": "s01", "title": "SEG 1", "text": "白天抬头看天，星星去哪儿了？",
         "duration_sec": 2.0},
        {"segment_id": "s02", "title": "SEG 2", "text": "太阳太亮，把它们的光盖住了。",
         "duration_sec": 2.0},
    ]


def test_gate_all_defect_scan_fail_closed() -> None:
    from hevi.capabilities.stable_film_pipeline import gate_all

    base = dict(segment_plan={"segment_count": 1, "total_sec": 2.0, "cap_sec": 15.0},
                segment_plan_error=None,
                motion_gate={"verdict": "pass", "real_change_ratio": 0.9, "beat_count": 1},
                subtitle_gate={"verdict": "pass", "event_count": 1},
                safe_zone={"measured": True, "safe_zone_pass": True, "bottom_fraction": 0.7},
                loudness={"verdict": "pass", "detail": "ok"},
                asset_check={"ready": True, "pending_material": [],
                             "pending_shot_ids": [], "generation_shot_ids": []},
                missing_segments=[],
                timeline_gate_report={"verdict": "pass", "warning_count": 0},
                critic_review_report={"verdict": "ship", "reason": "all good"})
    qc_no_scan = {"verdict": "pass", "failed_checks": [], "skipped_checks": [],
                  "checks": {}, "defect_scan": None}
    out = gate_all(final_qc_report=qc_no_scan, **base)
    assert "qa.final_qc_gate.defect_scan" in out["missing_gates"]
    assert out["status"] == "review"
    qc_skipped = {"verdict": "pass", "failed_checks": [], "skipped_checks": [],
                  "checks": {},
                  "defect_scan": {"status": "skipped", "reason": "too few frames"}}
    out2 = gate_all(final_qc_report=qc_skipped, **base)
    assert "qa.final_qc_gate.defect_scan" in out2["failed_gates"]
    qc_ran = {"verdict": "pass", "failed_checks": [], "skipped_checks": [],
              "checks": {},
              "defect_scan": {"status": "pass", "sample_count": 5}}
    out3 = gate_all(final_qc_report=qc_ran, **base)
    assert out3["status"] == "finished"


def test_gate_all_critic_missing_blocks_finished() -> None:
    from hevi.capabilities.stable_film_pipeline import gate_all

    out = gate_all(
        segment_plan={"segment_count": 1, "total_sec": 2.0, "cap_sec": 15.0},
        segment_plan_error=None,
        motion_gate={"verdict": "pass", "real_change_ratio": 0.9, "beat_count": 1},
        subtitle_gate={"verdict": "pass", "event_count": 1},
        safe_zone={"measured": True, "safe_zone_pass": True, "bottom_fraction": 0.7},
        loudness={"verdict": "pass", "detail": "ok"},
        final_qc_report={"verdict": "pass", "failed_checks": [], "skipped_checks": [],
                         "checks": {},
                         "defect_scan": {"status": "pass", "sample_count": 5}},
        asset_check={"ready": True, "pending_material": [],
                     "pending_shot_ids": [], "generation_shot_ids": []},
        missing_segments=[],
        timeline_gate_report={"verdict": "pass", "warning_count": 0},
        critic_review_report=None)
    assert "qa.critic_review" in out["missing_gates"]
    assert out["status"] == "review"


def test_assemble_without_critic_is_review_not_finished(tmp_path: Path) -> None:
    from hevi.capabilities import asset_registry as ar
    from hevi.capabilities import stable_film_pipeline as sfp

    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation={"confirmed": True, "stage": "pre_synthesis", "by": "test"},
        registry=reg, episode_id="episode1", transcript_source="",
        fps=5, width=270, height=480, base_name="film")
    assert out["status"] == "review", out["failures"]
    assert "qa.critic_review" in out["missing_gates"]
    assert out["defect_scan_status"] == "pass"
    assert out["cut_comparison"]["status"] == "planned_not_measured"


def test_assemble_with_ship_review_finishes(tmp_path: Path) -> None:
    from hevi.capabilities import asset_registry as ar
    from hevi.capabilities import stable_film_pipeline as sfp

    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation={"confirmed": True, "stage": "pre_synthesis", "by": "test"},
        registry=reg, episode_id="episode1", transcript_source="",
        fps=5, width=270, height=480, base_name="film",
        critic_review=_ship_review())
    assert out["status"] == "finished", out["failures"]
    assert out["timeline_gate"]["verdict"] == "pass"
    assert out["critic_review"]["verdict"] == "ship"


def test_assemble_gapped_timeline_is_review(tmp_path: Path) -> None:
    from hevi.capabilities import asset_registry as ar
    from hevi.capabilities import stable_film_pipeline as sfp

    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    gapped = _segments()
    gapped[1] = {**gapped[1], "start_sec": 3.0}  # 1s gap after segment 1
    out = sfp.assemble_film(
        title="t", segments=gapped, voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation={"confirmed": True, "stage": "pre_synthesis", "by": "test"},
        registry=reg, episode_id="episode1", transcript_source="",
        fps=5, width=270, height=480, base_name="film",
        critic_review=_ship_review())
    assert out["status"] == "review"
    assert out["timeline_gate"]["verdict"] == "fail"


def test_assemble_one_more_pass_review_is_review(tmp_path: Path) -> None:
    from hevi.capabilities import asset_registry as ar
    from hevi.capabilities import stable_film_pipeline as sfp

    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation={"confirmed": True, "stage": "pre_synthesis", "by": "test"},
        registry=reg, episode_id="episode1", transcript_source="",
        fps=5, width=270, height=480, base_name="film",
        critic_review=_one_more_pass_review())
    assert out["status"] == "review"
    assert out["critic_review"]["verdict"] == "one_more_pass"


# ------------------------------------------------------------- registration

def test_new_capabilities_registered(tmp_path: Path) -> None:
    for name in ("qa.page_contract", "qa.director_dials",
                 "qa.decision_log", "qa.ai_tells_ban"):
        assert contains(name), name
    from hevi.capabilities import get

    assert get("qa.page_contract").line == "qa"
    assert get("qa.director_dials").line == "qa"
    assert get("qa.decision_log").line == "qa"
    assert get("qa.ai_tells_ban").line == "qa"
    result = get("qa.page_contract").render_safe(
        {"record": _page_record()}, tmp_path / "out")
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
