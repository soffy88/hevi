"""Capability-level tests for koubo_cut.render."""

import hevi.capabilities as caps
from hevi.capabilities import get
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.koubo_cut import register_koubo_cut_capabilities_once


def test_koubo_cut_registered():
    assert "koubo_cut.render" in caps.names()
    cap = get("koubo_cut.render")
    assert cap.line == "koubo_cut"


def test_register_idempotent():
    before = set(caps.names())
    assert register_koubo_cut_capabilities_once() == []
    assert set(caps.names()) == before
