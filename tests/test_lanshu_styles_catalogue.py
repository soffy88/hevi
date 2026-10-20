"""Tests for the lanshu-explainer 12-style catalogue (styles.json)."""

from __future__ import annotations

import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent / "hevi" / "skills" / "lanshu-explainer"

REQUIRED_KEYS = {
    "key", "name_en", "name_cn", "kind", "look", "best_for",
    "script_guidance", "source_kit", "speed", "recap_length_s", "is_3d",
}

EXPECTED_KEYS = [
    "v1-editorial", "v2-signal", "v3-notebook", "v4-paper", "v5-comic",
    "v6-cinematic", "v7-drafting", "v8-chalkboard", "v9-clay",
    "v10-reasoning", "v11-casefile", "v12-sitcom",
]


def _catalogue() -> dict:
    return json.loads((SKILL_DIR / "styles.json").read_text(encoding="utf-8"))


def test_styles_json_loads_with_meta():
    data = _catalogue()
    assert "source" in data["meta"]
    assert "github.com/cclank/lanshu-create-ai-presenter-video" in data["meta"]["source"]
    assert "MIT" in data["meta"].get("source_ref", "") or "MIT" in json.dumps(data["meta"])


def test_twelve_styles_in_order():
    styles = _catalogue()["styles"]
    assert [s["key"] for s in styles] == EXPECTED_KEYS


def test_each_style_has_required_keys_and_kinds():
    for style in _catalogue()["styles"]:
        missing = REQUIRED_KEYS - set(style)
        assert not missing, f"{style['key']} missing {missing}"
        assert style["kind"] in ("visual", "narrative")
        assert style["key"].startswith("v")


def test_narrative_styles_have_arc():
    narratives = [s for s in _catalogue()["styles"] if s["kind"] == "narrative"]
    assert {s["key"] for s in narratives} == {"v10-reasoning", "v11-casefile", "v12-sitcom"}
    for style in narratives:
        assert style.get("arc"), f"{style['key']} narrative style needs an arc"


def test_kids_friendly_styles_present():
    styles = {s["key"]: s for s in _catalogue()["styles"]}
    for key in ("v8-chalkboard", "v3-notebook", "v4-paper", "v9-clay", "v5-comic"):
        assert key in styles
        assert styles[key]["best_for"], f"{key} needs a best_for"


def test_source_kits_use_upstream_paths():
    for style in _catalogue()["styles"]:
        assert style["source_kit"].startswith("explainer/kits/"), style["key"]
