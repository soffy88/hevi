"""Tests for storyboard lint rules covering all red and yellow flags."""

from hevi.motion_rules.lint import lint_storyboard


def test_clean_spec_passes() -> None:
    spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "is_loop": True,
        "first_frame": "frame_a",
        "last_frame": "frame_a",
        "shots": [
            {
                "start": 0.0,
                "dur": 2.0,
                "transition": {"start": 0.0, "type": "morph"},
                "container_morph": {"start": 0.2, "next_morph": 1.8},
                "texts": [{"text": "极简设计", "in": 0.3, "out": 1.7}],
                "effects": [],
            },
            {
                "start": 2.0,
                "dur": 2.0,
                "transition": {"start": 2.0, "type": "morph"},
                "container_morph": {"start": 2.2, "next_morph": 3.8},
                "texts": [{"text": "流畅动效", "in": 2.3, "out": 3.7}],
                "effects": [],
            },
        ],
    }
    report = lint_storyboard(spec)
    assert report.passed is True
    assert report.red_count == 0
    assert report.yellow_count == 0
    assert len(report.findings) == 0


def test_red_flag_prohibited_elements() -> None:
    # Triggered case
    banned_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 2.0,
                "effects": ["neon_glow", "shockwave_rings"],
                "easing": "bouncy",
            }
        ],
    }
    report = lint_storyboard(banned_spec)
    assert report.passed is False
    codes = [f.code for f in report.findings]
    assert codes.count("PROHIBITED_ELEMENT") == 3

    # Non-triggered case
    clean_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 2.0,
                "effects": ["gaussian_blur"],
                "easing": "closed_form_spring",
            }
        ],
    }
    clean_report = lint_storyboard(clean_spec)
    assert not any(f.code == "PROHIBITED_ELEMENT" for f in clean_report.findings)


def test_red_flag_bpm_grid_alignment() -> None:
    # Triggered case: BPM 120 (0.5s grid), transition at 0.65s (diff=0.15s > 0.02s)
    bad_grid_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.65,
                "dur": 2.0,
                "transition": {"start": 0.65},
            }
        ],
    }
    report = lint_storyboard(bad_grid_spec, bpm_tolerance=0.02)
    assert report.passed is False
    assert any(f.code == "BPM_GRID_MISALIGNMENT" for f in report.findings)

    # Non-triggered case: transition exactly at 1.0s (2 beats) or within 10ms tolerance
    good_grid_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 1.01,
                "dur": 2.0,
                "transition": {"start": 1.01},
            }
        ],
    }
    clean_report = lint_storyboard(good_grid_spec, bpm_tolerance=0.02)
    assert not any(f.code == "BPM_GRID_MISALIGNMENT" for f in clean_report.findings)


def test_red_flag_content_container_timing() -> None:
    # Triggered case 1: Text enters before container starts morphing
    bad_in_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 3.0,
                "container_morph": {"start": 0.4, "next_morph": 2.5},
                "texts": [{"text": "抢跑文字", "in": 0.2, "out": 2.0}],
            }
        ],
    }
    report_in = lint_storyboard(bad_in_spec)
    assert report_in.passed is False
    assert any(f.code == "TEXT_BEFORE_CONTAINER_MORPH" for f in report_in.findings)

    # Triggered case 2: Text leaves after container finishes or next morph starts
    bad_out_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 3.0,
                "container_morph": {"start": 0.4, "next_morph": 2.5},
                "texts": [{"text": "拖延文字", "in": 0.5, "out": 2.8}],
            }
        ],
    }
    report_out = lint_storyboard(bad_out_spec)
    assert report_out.passed is False
    assert any(f.code == "TEXT_AFTER_CONTAINER_MORPH" for f in report_out.findings)

    # Non-triggered case: text in 0.5 > 0.4, text out 2.3 < 2.5
    clean_timing_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 3.0,
                "container_morph": {"start": 0.4, "next_morph": 2.5},
                "texts": [{"text": "合规文字", "in": 0.5, "out": 2.3}],
            }
        ],
    }
    clean_report = lint_storyboard(clean_timing_spec)
    assert not any(f.code.startswith("TEXT_") for f in clean_report.findings)


def test_red_flag_text_contains_period() -> None:
    # Triggered cases: Chinese period '。' and English period '.'
    bad_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 2.0,
                "texts": [
                    {"text": "带有中文句号。"},
                    {"text": "With english period."},
                ],
            }
        ],
    }
    report = lint_storyboard(bad_spec)
    assert report.passed is False
    period_findings = [f for f in report.findings if f.code == "TEXT_CONTAINS_PERIOD"]
    assert len(period_findings) == 2

    # Non-triggered case: no period
    clean_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 2.0,
                "texts": [{"text": "干净精炼的短标题"}],
            }
        ],
    }
    clean_report = lint_storyboard(clean_spec)
    assert not any(f.code == "TEXT_CONTAINS_PERIOD" for f in clean_report.findings)


def test_red_flag_shot_duration_exceeded() -> None:
    # Triggered case: single shot dur 8.5s > 8.0s
    bad_dur_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 8.5,
            }
        ],
    }
    report = lint_storyboard(bad_dur_spec, max_shot_dur=8.0)
    assert report.passed is False
    assert any(f.code == "SHOT_DURATION_EXCEEDED" for f in report.findings)

    # Non-triggered case: single shot dur 6.0s <= 8.0s
    clean_dur_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [
            {
                "start": 0.0,
                "dur": 6.0,
            }
        ],
    }
    clean_report = lint_storyboard(clean_dur_spec, max_shot_dur=8.0)
    assert not any(f.code == "SHOT_DURATION_EXCEEDED" for f in clean_report.findings)


def test_yellow_flags_contact_sheet_and_loop() -> None:
    # Triggered: missing contact sheet
    no_cs_spec = {
        "bpm": 120.0,
        "has_contact_sheet": False,
        "shots": [{"start": 0.0, "dur": 2.0}],
    }
    report_cs = lint_storyboard(no_cs_spec)
    assert report_cs.passed is True  # Yellow warnings do not block pass
    assert any(f.code == "MISSING_CONTACT_SHEET" and f.level == "yellow" for f in report_cs.findings)

    # Non-triggered: contact sheet present
    with_cs_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "shots": [{"start": 0.0, "dur": 2.0}],
    }
    report_with_cs = lint_storyboard(with_cs_spec)
    assert not any(f.code == "MISSING_CONTACT_SHEET" for f in report_with_cs.findings)

    # Triggered: loop frame mismatch
    bad_loop_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "is_loop": True,
        "first_frame": "frame_001",
        "last_frame": "frame_999",
        "shots": [{"start": 0.0, "dur": 2.0}],
    }
    report_loop = lint_storyboard(bad_loop_spec)
    assert report_loop.passed is True
    assert any(f.code == "LOOP_FRAME_MISMATCH" and f.level == "yellow" for f in report_loop.findings)

    # Non-triggered: loop frame matches
    good_loop_spec = {
        "bpm": 120.0,
        "has_contact_sheet": True,
        "is_loop": True,
        "first_frame": "frame_001",
        "last_frame": "frame_001",
        "shots": [{"start": 0.0, "dur": 2.0}],
    }
    report_good_loop = lint_storyboard(good_loop_spec)
    assert not any(f.code == "LOOP_FRAME_MISMATCH" for f in report_good_loop.findings)
