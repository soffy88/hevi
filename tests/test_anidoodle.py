"""S29 anidoodle: catalog, attribution, safe area and capability registration."""

from __future__ import annotations

import pytest

from hevi.anidoodle import (
    AnidoodleError,
    check_safe_area,
    families,
    get_style,
    list_styles,
    recommend_style,
)
from hevi.anidoodle.engine import engine_dir, node_binary


def _engine_ready() -> bool:
    try:
        node_binary()
    except AnidoodleError:
        return False
    engine = engine_dir()
    return (engine / "node_modules" / "playwright-core").is_dir()


def test_catalog_has_32_styles_and_media_groups() -> None:
    styles = list_styles()
    assert len(styles) == 32
    assert len({style.id for style in styles}) == 32
    groups = families()
    assert len(groups) >= 10
    assert sum(len(group["styles"]) for group in groups) == 32


def test_style_draw_films_are_named() -> None:
    for style in list_styles():
        assert style.draw_film
        assert style.name
        assert style.medium


def test_recommend_is_explainable_and_avoids_blocked() -> None:
    result = recommend_style("灯塔为什么建在礁石上", intent="explainer")
    assert result["style"]["id"] == "lighthouse"
    assert result["reason"]
    assert len(result["alternatives"]) == 2
    blocked = recommend_style("灯塔", intent="explainer", avoid=["lighthouse"])
    assert blocked["style"]["id"] != "lighthouse"


def test_unknown_style_fails_closed() -> None:
    with pytest.raises(AnidoodleError):
        get_style("not-a-style")


def test_safe_area_s26_vertical() -> None:
    width, height = 1080, 1920
    good = check_safe_area(
        [{"x0": 60, "y0": 150, "x1": 940, "y1": 1540}],
        width=width,
        height=height,
    )
    assert good["ok"] is True
    bad = check_safe_area(
        [{"x0": 20, "y0": 120, "x1": 1000, "y1": 1600}],
        width=width,
        height=height,
    )
    assert bad["ok"] is False
    assert set(bad["failures"][0]["edges"]) == {"left", "top", "right", "bottom"}
    empty = check_safe_area([], width=width, height=height)
    assert empty["ok"] is None
    assert empty["status"] == "not_applicable"


def test_capabilities_registered() -> None:
    from hevi.capabilities import registry

    names = set(registry.names())
    for name in (
        "anidoodle.style_list",
        "anidoodle.still",
        "anidoodle.draw_clip",
        "anidoodle.music",
        "anidoodle.gate",
    ):
        assert name in names


@pytest.mark.skipif(not _engine_ready(), reason="anidoodle Node deps/browser not installed")
def test_engine_probe_reports_node_and_browser() -> None:
    from hevi.anidoodle import engine_info

    info = engine_info()
    assert info.node_major >= 20
    assert info.npm_deps is True
    assert "headless" in info.browser or "chrome" in info.browser


# --- S30: optional sound pack -------------------------------------------


def _write_pack(root, instruments, rooms=None) -> None:
    import json

    data = {
        "pack": "anidoodle-sounds",
        "version": 1,
        "instruments": instruments,
        "rooms": rooms or {},
    }
    (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


def _zone(root, name: str, body: bytes = b"x") -> dict:
    import hashlib

    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(body)
    return {"file": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def test_soundpack_absent_is_reported_not_raised(tmp_path, monkeypatch) -> None:
    from hevi.anidoodle import soundpack

    monkeypatch.setenv("HEVI_ANIDOODLE_SOUNDS", str(tmp_path / "nope"))
    status = soundpack.pack_status()
    assert status["installed"] is False and status["enabled"] is False
    assert soundpack.render_env() == {}
    assert soundpack.pack_status(verify=True)["installed"] is False


def test_soundpack_withholds_a_non_cc0_instrument(tmp_path, monkeypatch) -> None:
    from hevi.anidoodle import soundpack

    monkeypatch.setenv("HEVI_ANIDOODLE_SOUNDS", str(tmp_path))
    _write_pack(
        tmp_path,
        {
            "piano": {"license": "CC0-1.0", "zones": [_zone(tmp_path, "piano/C4.flac")]},
            "paid": {"license": "CC-BY-NC-4.0", "zones": [_zone(tmp_path, "paid/C4.flac")]},
        },
    )
    status = soundpack.pack_status()
    assert [row["id"] for row in status["instruments"]] == ["piano"]
    assert [row["id"] for row in status["withheld"]] == ["paid"]
    assert status["enabled"] is True
    assert soundpack.render_env()["ANIDOODLE_SOUNDS"] == str(tmp_path)


def test_soundpack_room_licence_and_verify(tmp_path, monkeypatch) -> None:
    from hevi.anidoodle import soundpack

    monkeypatch.setenv("HEVI_ANIDOODLE_SOUNDS", str(tmp_path))
    zone = _zone(tmp_path, "rooms/hall.flac", b"ir")
    _write_pack(
        tmp_path,
        {},
        {
            "hall": {
                "title": "Hall",
                "license": "CC-BY-4.0",
                "file": zone["file"],
                "sha256": zone["sha256"],
            }
        },
    )
    status = soundpack.pack_status(verify=True)
    assert status["rooms"][0]["mb"] == round(len(b"ir") / 1e6, 2)
    assert "OpenAIR" in status["credit"]
    assert status["verify"] == {"ok": True, "files": 1, "failures": []}
    zone_path = tmp_path / zone["file"]
    zone_path.write_bytes(b"tampered")
    bad = soundpack.pack_status(verify=True)["verify"]
    assert bad["ok"] is False and bad["failures"]


def test_compose_defaults_to_code_when_pack_absent(tmp_path, monkeypatch) -> None:
    from hevi.anidoodle import soundpack

    monkeypatch.setenv("HEVI_ANIDOODLE_SOUNDS", str(tmp_path / "nope"))
    material, recorded = __import__(
        "hevi.anidoodle.music", fromlist=["_material"]
    )._material(
        "folk", mood="", key="", bpm=0, bars=8, seed=30, sound="auto"
    )
    assert recorded is True
    assert "voices" in material  # the score asks; the engine falls back per slot
    assert soundpack.render_env() == {}


def test_voice_credits_drops_none_and_keeps_parentheses() -> None:
    from hevi.anidoodle.music import _voice_credits

    assert _voice_credits("none") == []
    assert _voice_credits("chords (warmPad), lead (softPluck)") == [
        "chords (warmPad)",
        "lead (softPluck)",
    ]
    assert _voice_credits(
        "chords (piano), lead (marimba, sparse, max shift 3 semitones), counter (vibes)"
    ) == [
        "chords (piano)",
        "lead (marimba, sparse, max shift 3 semitones)",
        "counter (vibes)",
    ]


@pytest.mark.skipif(not _engine_ready(), reason="anidoodle engine deps missing")
def test_code_mode_reports_no_recordings(tmp_path) -> None:
    from hevi.anidoodle import music

    result = music.compose_bgm(style="musicBox", bars=6, seed=30, sound="code", fmt="wav")
    assert result["sound"]["used"] == "code"
    assert result["sound"]["recordings"] == []
    assert result["sound"]["modeled"]
