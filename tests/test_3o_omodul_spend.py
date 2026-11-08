"""Guard tests: 3O omodul standard-form contract + spend-gate wiring."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hevi.capabilities import errors as cap_errors
from hevi.capabilities.layer_attribution import LAYER_ATTRIBUTION
from hevi.capabilities.omodul_contract import (
    OMODUL_PILLARS,
    PILLARS,
    enabled_pillars,
    omodul_entry,
    omodul_names,
    run_omodul,
)
from hevi.capabilities.registry import get as caps_get
from hevi.capabilities.result import CapabilityResult

BOARD = [{"shot_id": "s1", "visual": "a still lake", "duration_sec": 5.0}]
APPROVAL = {
    "storyboard": BOARD,
    "confirmed": True,
    "smoke_passed": True,
    "batch_size": 1,
}


def test_omodul_pillars_cover_all_attributed():
    names = [n for n, e in LAYER_ATTRIBUTION.items() if e["layer"] == "omodul"]
    # 51 from origin/main + 4 merged (koubo_cut.render, collage_broll.*).
    assert len(names) == 55
    assert set(OMODUL_PILLARS) == set(names)
    assert set(omodul_names()) == set(names)
    for name, pillars in OMODUL_PILLARS.items():
        assert pillars, name
        assert pillars <= PILLARS, (name, pillars)
        assert "fingerprint" in pillars and "report" in pillars, name
    assert OMODUL_PILLARS["story.film_from_prompt"] >= {"cost"}
    assert OMODUL_PILLARS["pipeline.project_handoff"] >= {"decision_trail"}


def test_enabled_pillars_fails_closed():
    with pytest.raises(cap_errors.CapabilityError):
        enabled_pillars("qa.no_such_capability")
    with pytest.raises(cap_errors.CapabilityError):
        enabled_pillars("qa.prompt_compiler")  # oskill, not omodul


def test_adapter_success_envelope(monkeypatch, tmp_path):
    fake = CapabilityResult(mp4=str(tmp_path / "x.mp4"), duration_s=5.0,
                            sha256="abc", qa={"verdict": "pass"})
    cap = caps_get("story.generation_unit_splitter")
    monkeypatch.setattr(cap, "render_safe", lambda *a, **k: fake)
    out = run_omodul("story.generation_unit_splitter", {}, {"prompt": "x"},
                     tmp_path)
    assert out["status"] == "ok"
    assert out["error"] is None
    assert out["capability"] == "story.generation_unit_splitter"
    assert out["pillars"] == ["fingerprint", "report"]
    assert out["result"]["sha256"] == "abc"


def test_adapter_failure_never_raises(monkeypatch, tmp_path):
    cap = caps_get("story.generation_unit_splitter")

    def boom(*a, **k):
        raise RuntimeError("workflow exploded")

    monkeypatch.setattr(cap, "render_safe", boom)
    out = run_omodul("story.generation_unit_splitter", {}, {}, tmp_path)
    assert out["status"] == "failed"
    assert "RuntimeError" in out["error"] and "exploded" in out["error"]
    assert out["pillars"] == ["fingerprint", "report"]


def test_adapter_reraises_cancellation(monkeypatch, tmp_path):
    cap = caps_get("story.generation_unit_splitter")

    def cancel(*a, **k):
        raise asyncio.CancelledError()

    monkeypatch.setattr(cap, "render_safe", cancel)
    with pytest.raises(asyncio.CancelledError):
        run_omodul("story.generation_unit_splitter", {}, {}, tmp_path)


def test_adapter_real_end_to_end(tmp_path):
    # generation_unit_splitter is pure splitting: a real call needs no
    # keys, GPU, or network. If its params change, this test -- not a
    # monkeypatch -- is what catches it.
    out = run_omodul(
        "story.generation_unit_splitter",
        {},
        {"shots": [{"id": "s1", "scene": "lake", "start_s": 0.0, "end_s": 5.0}]},
        tmp_path,
    )
    assert out["status"] == "ok", out
    assert out["result"]["sha256"]


def test_spend_gate_refusal_precedes_key_and_network(monkeypatch, tmp_path):
    # No keys in the environment: a refused approval must surface as a
    # spend refusal, never as a missing-key error -- proving the gate
    # runs before any key read or network call.
    for key in ("PIXSTAG_API_KEY", "MONID_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    denied = dict(APPROVAL, confirmed=False)
    for name, params in (
        ("video.pixstag_generate", {"prompt": "x", "spend_approval": denied}),
        ("image.gpt_generate", {"prompt": "x", "spend_approval": denied}),
        ("image.gpt_edit", {"prompt": "x", "image_paths": ["a.png"],
                            "spend_approval": denied}),
        ("image.nano_banana_generate",
         {"prompt": "x", "allow_paid": True, "spend_approval": denied}),
        ("video.fasth3_local",
         {"reference_image": "r.jpg", "prompt": "x", "spend_approval": denied}),
    ):
        with pytest.raises(cap_errors.CapabilityError, match="paid generation refused"):
            caps_get(name).render_safe(params, tmp_path, duration=5.0,
                                        aspect="16:9", seed=1)


def test_spend_gate_approved_passes_gate_but_still_needs_key(
    monkeypatch, tmp_path
):
    # Approved: the gate lets the call through, so the NEXT failure is
    # the missing key / unreachable service -- proving approval is not
    # itself a refusal and not a fake pass.
    for key in ("PIXSTAG_API_KEY", "MONID_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(cap_errors.CapabilityError) as exc:
        caps_get("video.pixstag_generate").render_safe(
            {"prompt": "x", "spend_approval": APPROVAL},
            tmp_path, duration=5.0, aspect="16:9", seed=1,
        )
    assert "paid generation refused" not in str(exc.value)


def test_spend_gate_absent_records_caller_responsibility(monkeypatch):
    # nano_banana refuses without allow_paid; with allow_paid + no
    # spend_approval, the call must reach the key/network stage (and
    # fail there offline), proving absence is caller-side, not a gate.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(cap_errors.CapabilityError) as exc:
        caps_get("image.nano_banana_generate").render_safe(
            {"prompt": "x", "allow_paid": True},
            Path("/tmp"), duration=5.0, aspect="16:9", seed=1,
        )
    assert "paid generation refused" not in str(exc.value)
