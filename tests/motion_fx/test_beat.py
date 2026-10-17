"""Tests for BPM grid snapping."""

import pytest
from hevi.motion_fx.beat import (
    generate_beat_grid,
    get_grid_step,
    parse_division,
    snap_to_grid,
)


def test_parse_division():
    assert parse_division(4) == 4.0
    assert parse_division("4") == 4.0
    assert parse_division("1/4") == 4.0
    assert parse_division("1/8") == 8.0
    assert parse_division("1/16") == 16.0
    assert parse_division(8) == 8.0

    with pytest.raises(ValueError):
        parse_division(0)
    with pytest.raises(ValueError):
        parse_division(-4)
    with pytest.raises(ValueError):
        parse_division("invalid")


def test_get_grid_step():
    # At 120 BPM:
    # 1 beat = 60 / 120 = 0.5s (quarter note, div=4)
    assert get_grid_step(120.0, 4) == pytest.approx(0.5)
    # Eighth note (div=8) = 0.25s
    assert get_grid_step(120.0, 8) == pytest.approx(0.25)
    # Sixteenth note (div=16) = 0.125s
    assert get_grid_step(120.0, 16) == pytest.approx(0.125)
    # Whole note (div=1) = 2.0s
    assert get_grid_step(120.0, 1) == pytest.approx(2.0)

    # At 60 BPM:
    # Quarter note = 1.0s
    assert get_grid_step(60.0, 4) == pytest.approx(1.0)


def test_snap_to_grid_quarter_notes():
    # 120 BPM, quarter notes (step = 0.5s)
    assert snap_to_grid(0.1, bpm=120, division=4) == 0.0
    assert snap_to_grid(0.26, bpm=120, division=4) == 0.5
    assert snap_to_grid(0.49, bpm=120, division=4) == 0.5
    assert snap_to_grid(0.74, bpm=120, division=4) == 0.5
    assert snap_to_grid(0.76, bpm=120, division=4) == 1.0
    assert snap_to_grid(1.24, bpm=120, division=4) == 1.0
    assert snap_to_grid(1.26, bpm=120, division=4) == 1.5


def test_snap_to_grid_eighth_notes():
    # 120 BPM, 8th notes (step = 0.25s)
    assert snap_to_grid(0.1, bpm=120, division=8) == 0.0
    assert snap_to_grid(0.14, bpm=120, division=8) == 0.25
    assert snap_to_grid(0.36, bpm=120, division=8) == 0.25
    assert snap_to_grid(0.38, bpm=120, division=8) == 0.5


def test_snap_to_grid_clamped():
    # Negative time clamped to min_time
    assert snap_to_grid(-0.2, bpm=120, division=4, min_time=0.0) == 0.0


def test_generate_beat_grid():
    grid = generate_beat_grid(duration=2.0, bpm=120, division=4)
    assert grid == [0.0, 0.5, 1.0, 1.5, 2.0]
