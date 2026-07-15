"""capture_source 根变量库测试(HEVI 路线图 Phase3 #38)。"""

from __future__ import annotations

from hevi.style.capture_source import (
    CAPTURE_SOURCE_PRESETS,
    list_capture_sources,
    resolve_capture_source,
)


def test_resolve_capture_source_known_entry():
    r = resolve_capture_source("2000s_home_dv")
    assert "camera" in r and "lighting" in r and "negative" in r


def test_resolve_capture_source_unknown_returns_empty_dict():
    assert resolve_capture_source("not-a-real-source") == {}


def test_resolve_capture_source_empty_string_returns_empty_dict():
    assert resolve_capture_source("") == {}


def test_list_capture_sources_matches_dict_keys():
    assert list_capture_sources() == list(CAPTURE_SOURCE_PRESETS)


def test_all_presets_have_the_three_derivable_fields():
    for name, preset in CAPTURE_SOURCE_PRESETS.items():
        assert set(preset) == {"camera", "lighting", "negative"}, name
