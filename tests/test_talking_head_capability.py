"""Capability-level tests for talking_head.render (G14).

No GPU / TTS / lip-sync is exercised here: the full pipeline path is
covered by tests/test_talking_head_pipeline.py (injected stage fns).
These tests pin the registry wiring and the fast failure modes only.
"""

import hevi.capabilities as caps
from hevi.capabilities import get
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.talking_head import register_talking_head_capabilities_once


def test_talking_head_registered_in_unified_entry():
    assert "talking_head.render" in caps.names()
    cap = get("talking_head.render")
    assert cap.line == "talking_head"
    assert cap.aspects == ["1:1"]


def test_register_is_idempotent():
    before = set(caps.names())
    assert register_talking_head_capabilities_once() == []
    assert set(caps.names()) == before


def test_render_rejects_missing_portrait(tmp_path):
    cap = get("talking_head.render")
    try:
        cap.render_safe(
            {"script_text": "你好", "portrait_path": str(tmp_path / "nope.jpg")},
            tmp_path / "out",
        )
    except CapabilityError as exc:
        assert "portrait not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected CapabilityError for missing portrait")


def test_render_rejects_empty_script(tmp_path):
    cap = get("talking_head.render")
    try:
        cap.render_safe(
            {"script_text": "", "portrait_path": str(tmp_path / "x.jpg")},
            tmp_path / "out",
        )
    except CapabilityError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected CapabilityError for empty script")
