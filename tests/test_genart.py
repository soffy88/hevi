"""Tests for the generative-art engine + image.generative_art.

Offline and CPU-only: determinism of the flow-field simulation and
of rendered pixels, spec validation, palette resolution, the exact
video-loop property, capability registration and real (tiny) renders.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hevi.image.genart import (
    PALETTES,
    SpecError,
    julia_mu,
    loop_life,
    parse_spec,
    render_still,
    render_video,
    resolve_palette,
    simulate_flowfield,
)

SMALL = {"width": 288, "height": 192}


def _flow_spec(**over):
    base = {
        "algorithm": "flowfield",
        "seed": 7,
        "palette": "abyss",
        "particle_count": 300,
        "particle_life": 120,
        **SMALL,
    }
    base.update(over)
    return parse_spec(base)


def _img_hash(img) -> str:
    return hashlib.sha256(img.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_flowfield_determinism_same_seed() -> None:
    a = simulate_flowfield(_flow_spec())
    b = simulate_flowfield(_flow_spec())
    assert (a.trajectories == b.trajectories).all()
    assert (a.hues == b.hues).all()
    assert (a.phases == b.phases).all()
    assert a.trajectories.shape == (300, 121, 2)


def test_flowfield_different_seed_differs() -> None:
    a = simulate_flowfield(_flow_spec())
    b = simulate_flowfield(_flow_spec(seed=8))
    assert not (a.trajectories == b.trajectories).all()


def test_still_render_is_byte_deterministic() -> None:
    spec = _flow_spec()
    h1 = _img_hash(render_still(spec)[0])
    h2 = _img_hash(render_still(spec)[0])
    assert h1 == h2


def test_still_different_seed_differs() -> None:
    assert _img_hash(render_still(_flow_spec())[0]) != _img_hash(
        render_still(_flow_spec(seed=99))[0]
    )


def test_julia_deterministic() -> None:
    spec = parse_spec(
        {"algorithm": "julia", "seed": 3, "max_iter": 40, **SMALL}
    )
    assert (julia_mu(spec) == julia_mu(spec)).all()
    assert _img_hash(render_still(spec)[0]) == _img_hash(render_still(spec)[0])


# ---------------------------------------------------------------------------
# Spec validation / palettes
# ---------------------------------------------------------------------------


def test_spec_validation_errors() -> None:
    with pytest.raises(SpecError):
        parse_spec({"algorithm": "plasma"})
    with pytest.raises(SpecError):
        parse_spec({"bogus_key": 1})
    with pytest.raises(SpecError):
        parse_spec({"palette": "no-such-palette"})
    with pytest.raises(SpecError):
        parse_spec({"colors": ["#zzzzzz", "#112233"]})
    with pytest.raises(SpecError):
        parse_spec({"colors": ["#112233"]})
    with pytest.raises(SpecError):
        parse_spec({"particle_count": 5})
    with pytest.raises(SpecError):
        parse_spec({"width": 32})
    with pytest.raises(SpecError):
        parse_spec({"seed": "seven"})


def test_palette_resolution() -> None:
    assert resolve_palette("ember").name == "ember"
    assert resolve_palette(None).name == "abyss"
    custom = resolve_palette(["#0b1030", "#e85d1e", "#ffe8a8"])
    assert custom.name == "custom"
    assert len(custom.stops) == 3
    assert set(PALETTES) == {"ember", "abyss", "sakura", "verdant"}
    for pal in PALETTES.values():
        assert pal.lut(16).shape == (16, 3)


def test_julia_c_forms() -> None:
    spec = parse_spec({"algorithm": "julia", "julia_c": [-0.8, 0.156]})
    assert spec.julia_c == complex(-0.8, 0.156)
    with pytest.raises(SpecError):
        parse_spec({"algorithm": "julia", "julia_c": "nope"})


# ---------------------------------------------------------------------------
# Loop property
# ---------------------------------------------------------------------------


def test_loop_life_divides_frame_count() -> None:
    assert 240 % loop_life(240, 220) == 0
    assert loop_life(240, 220) <= 220
    assert loop_life(240, 240) == 240
    assert loop_life(96, 48) == 48


def test_video_loop_frame_exact() -> None:
    from dataclasses import replace

    from hevi.image.genart import render_flow_frame

    spec = _flow_spec(particle_count=60, particle_life=24)
    total = 24
    life = loop_life(total, spec.particle_life)
    sim = simulate_flowfield(replace(spec, particle_life=life))
    f0 = render_flow_frame(spec, sim, 0, total, life)
    f_end = render_flow_frame(spec, sim, total, total, life)
    assert f0.tobytes() == f_end.tobytes()


# ---------------------------------------------------------------------------
# Real (tiny) video renders
# ---------------------------------------------------------------------------


def test_tiny_flowfield_video(tmp_path: Path) -> None:
    spec = parse_spec(
        {
            "algorithm": "flowfield",
            "seed": 11,
            "particle_count": 60,
            "particle_life": 24,
            "width": 160,
            "height": 96,
        }
    )
    out = tmp_path / "flow.mp4"
    stats = render_video(spec, out, seconds=1.0, fps=12)
    assert out.is_file() and stats["file_bytes"] > 0
    assert stats["frames"] == 12
    assert stats["cost"] == 0.0


def test_tiny_julia_video(tmp_path: Path) -> None:
    spec = parse_spec(
        {"algorithm": "julia", "seed": 5, "max_iter": 30, "width": 160, "height": 96}
    )
    out = tmp_path / "julia.mp4"
    stats = render_video(spec, out, seconds=1.0, fps=8)
    assert out.is_file() and stats["file_bytes"] > 0
    assert stats["frames"] == 8


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


def test_capability_registered() -> None:
    import hevi.capabilities.generative_art  # noqa: F401
    from hevi.capabilities.registry import contains, get

    assert contains("image.generative_art")
    cap = get("image.generative_art")
    assert cap.kind == "shot"
    assert cap.line == "image"


def test_capability_still_render(tmp_path: Path) -> None:
    import hevi.capabilities.generative_art  # noqa: F401
    from hevi.capabilities.registry import get

    cap = get("image.generative_art")
    result = cap.render(
        {
            "algorithm": "flowfield",
            "palette": "ember",
            "width": 288,
            "height": 192,
            "particle_count": 200,
            "particle_life": 60,
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=5,
    )
    assert result.png is not None
    assert Path(result.png).is_file()
    assert result.sha256
    assert result.qa["cost"] == 0.0
    assert result.qa["palette"] == "ember"


def test_capability_rejects_bad_params(tmp_path: Path) -> None:
    import hevi.capabilities.generative_art  # noqa: F401
    from hevi.capabilities.errors import CapabilityError
    from hevi.capabilities.registry import get

    cap = get("image.generative_art")
    with pytest.raises(CapabilityError):
        cap.render({"mode": "spin"}, tmp_path, duration=0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render(
            {"palette": "nope"}, tmp_path, duration=0, aspect="16:9", seed=1
        )
