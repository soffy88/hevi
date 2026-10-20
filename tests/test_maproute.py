"""Contract tests for the map-route capability (CAPABILITY_CONTRACT.md).

Offline: geocoding / routing / tile HTTP is injected via fake fetchers,
frame capture is injected via a fake capture function, so no network, no
paid call and no Chromium are needed.  ffmpeg (present on the host) does
the real encode for the render test.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.maproute import geo, timeline
from hevi.maproute.errors import MapRouteError
from hevi.maproute.render import render_map_route
from hevi.maproute.schema import validate_shot_table

BEIJING = {"name": "北京", "lat": 39.9042, "lon": 116.4074, "narration": "我们从北京出发"}
TIANJIN = {"name": "天津", "lat": 39.1252, "lon": 117.2008, "narration": "第一站来到天津"}
JINAN = {"name": "济南", "lat": 36.6512, "lon": 117.1201, "narration": "最后抵达济南"}


def _table(**overrides):
    table = {"title": "南下之旅", "stops": [dict(BEIJING), dict(TIANJIN), dict(JINAN)]}
    table.update(overrides)
    return table


# ------------------------------------------------------------- registration

def test_maproute_capability_registered_and_listable() -> None:
    assert "video.map_route" in caps.names()
    listed = [c.name for c in caps.list(kind="shot")]
    assert "video.map_route" in listed


def test_maproute_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    assert "video.map_route" in by_name
    item = by_name["video.map_route"]
    assert item.get("description")
    assert "free" in item["description"].lower()
    schema = item.get("params_schema") or {}
    assert "stops" in (schema.get("properties") or {})


# ------------------------------------------------------------ schema checks

def test_shot_table_validation() -> None:
    ok = validate_shot_table(_table())
    assert [s["name"] for s in ok["stops"]] == ["北京", "天津", "济南"]
    assert ok["stops"][0]["camera"] == "follow"  # default
    with pytest.raises(MapRouteError):
        validate_shot_table({"stops": [dict(BEIJING)]})  # < 2 stops
    with pytest.raises(MapRouteError):
        validate_shot_table(_table(stops=[dict(BEIJING), {"name": "x", "camera": "zoom"}]))
    with pytest.raises(MapRouteError):  # lat without lon
        validate_shot_table(_table(stops=[dict(BEIJING), {"name": "x", "lat": 30.0}]))
    with pytest.raises(MapRouteError):
        validate_shot_table(_table(provider="google"))
    with pytest.raises(MapRouteError):
        validate_shot_table(_table(stops=[dict(BEIJING), {"name": "x", "dwell_s": 99}]))


def test_capability_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("video.map_route")
    with pytest.raises(CapabilityError):  # bad provider enum (jsonschema)
        cap.render_safe(
            {"provider": "google", "stops": [BEIJING, TIANJIN]},
            tmp_path, duration=5.0, aspect="16:9", seed=1,
        )
    with pytest.raises(CapabilityError):  # only one stop (jsonschema minItems)
        cap.render_safe(
            {"stops": [BEIJING]}, tmp_path, duration=5.0, aspect="16:9", seed=1
        )
    with pytest.raises(CapabilityError):  # additional property
        cap.render_safe(
            {"stops": [BEIJING, TIANJIN], "bogus": 1},
            tmp_path, duration=5.0, aspect="16:9", seed=1,
        )
    with pytest.raises(CapabilityError):  # semantic: bad camera reaches render
        cap.render_safe(
            {"stops": [BEIJING, {**TIANJIN, "camera": "orbit"}]},
            tmp_path, duration=5.0, aspect="16:9", seed=1,
        )


# ------------------------------------------------------------- amap key gate

def test_amap_without_key_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HEVI_AMAP_KEY", raising=False)
    cap = caps.get("video.map_route")
    with pytest.raises(CapabilityError) as excinfo:
        cap.render_safe(
            {"provider": "amap", "stops": [{"name": "北京"}, {"name": "天津"}]},
            tmp_path, duration=5.0, aspect="16:9", seed=1,
        )
    message = str(excinfo.value)
    assert "HEVI_AMAP_KEY" in message
    assert "osm" in message.lower()


# ------------------------------------------------------------------ geo layer

def _no_network(url, headers):  # pragma: no cover - guard
    raise AssertionError(f"network must not be called: {url}")


def test_geocode_gazetteer_needs_no_network() -> None:
    hit = geo.geocode_place("北京", fetcher=_no_network)
    assert hit["source"] == "gazetteer"
    assert abs(hit["lon"] - 116.4074) < 1e-6


def test_geocode_photon_via_mock_fetcher() -> None:
    def fake_fetch(url, headers):
        assert "photon.komoot.io" in url
        payload = {
            "features": [
                {
                    "geometry": {"coordinates": [120.0, 30.0]},
                    "properties": {"name": "某地"},
                }
            ]
        }
        return json.dumps(payload).encode()

    hit = geo.geocode_place("某地", fetcher=fake_fetch)
    assert hit["source"] == "photon"
    assert hit["lon"] == 120.0 and hit["lat"] == 30.0


def test_route_osrm_via_mock_fetcher() -> None:
    def fake_fetch(url, headers):
        assert "router.project-osrm.org" in url
        payload = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 120000.0,
                    "duration": 5400.0,
                    "geometry": {
                        "coordinates": [[116.4, 39.9], [116.9, 39.5], [117.2, 39.1]]
                    },
                }
            ],
        }
        return json.dumps(payload).encode()

    route = geo.fetch_route(
        [(116.4074, 39.9042), (117.2008, 39.1252)], fetcher=fake_fetch
    )
    assert route["source"] == "osrm"
    assert route["distance_m"] == 120000.0
    assert len(route["polyline"]) == 3


# ------------------------------------------------------------------ timeline

def _alignment_for(stops) -> dict:
    """Fake whisper_local-shaped alignment: 0.4 s per narration character."""
    words = []
    t_ms = 0
    for stop in stops:
        for ch in stop["narration"]:
            words.append({"text": ch, "start_ms": t_ms, "end_ms": t_ms + 400})
            t_ms += 400
        t_ms += 600  # pause between segments
    return {
        "alignment_source": "whisper_asr_local",
        "is_estimated": False,
        "duration_ms": t_ms,
        "words": words,
    }


def test_timeline_alignment_driven() -> None:
    stops = validate_shot_table(_table())["stops"]
    alignment = _alignment_for(stops)
    result = timeline.build_timeline(stops, [0.0, 0.45, 1.0], alignment=alignment)
    assert result["mode"] == "alignment"
    milestones = result["milestones"]
    assert milestones[0] == (0.0, 0.0)
    assert milestones[-1][1] == 1.0
    times = [t for t, _ in milestones]
    assert times == sorted(times)
    # Route reaches Tianjin exactly when its narration segment ends:
    seg2_end = max(
        w["end_ms"] for w in alignment["words"][: len("我们从北京出发第一站来到天津")]
    ) / 1000.0
    frac_at_seg2 = timeline.fraction_at(milestones, seg2_end)
    assert abs(frac_at_seg2 - 0.45) < 1e-6
    assert timeline.fraction_at(milestones, 0.0) == 0.0


def test_timeline_dwell_driven() -> None:
    stops = validate_shot_table(_table())["stops"]
    result = timeline.build_timeline(stops, [0.0, 0.45, 1.0])
    assert result["mode"] == "dwell"
    assert result["total_duration_s"] > 0
    assert timeline.fraction_at(result["milestones"], 0.0) == 0.0
    assert timeline.fraction_at(result["milestones"], result["total_duration_s"]) == 1.0


def test_timeline_alignment_missing_first_segment_fails() -> None:
    stops = validate_shot_table(_table())["stops"]
    bad = {"words": [{"text": "无", "start_ms": 0, "end_ms": 100}]}
    with pytest.raises(MapRouteError):
        timeline.build_timeline(stops, [0.0, 0.45, 1.0], alignment=bad)


def test_parse_alignment_accepts_storyfilm_shape() -> None:
    data = {
        "alignment_source": "elevenlabs_forced_alignment",
        "is_estimated": False,
        "duration_ms": 900,
        "words": [
            {"text": "小", "start_ms": 140, "end_ms": 200},
            {"text": "雨", "start_ms": 200, "end_ms": 320},
        ],
    }
    words = timeline.parse_alignment(data)
    assert words[0]["end_s"] == pytest.approx(0.2)
    assert words[1]["start_s"] == pytest.approx(0.2)


# -------------------------------------------------------------- offline render

def _fake_capture(html_path, frames_dir, *, fps, total_s, width, height):
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    assert Path(html_path).is_file()
    n = max(2, int(round(total_s * fps)))
    for i in range(n):
        Image.new("RGB", (width, height), (30 + i * 3 % 200, 60, 90)).save(
            frames_dir / f"frame_{i:04d}.png"
        )
    return n


def _fake_tiles(url, headers):
    if "arcgisonline" in url:
        buf = Path(__file__).parent  # not used; build a tile in-memory
        from io import BytesIO

        bio = BytesIO()
        Image.new("RGB", (256, 256), (240, 238, 230)).save(bio, format="PNG")
        return bio.getvalue()
    raise AssertionError(f"unexpected url: {url}")


def test_render_offline_with_injected_seams(tmp_path: Path) -> None:
    table = _table(
        route_polyline=[[116.4074, 39.9042], [116.9, 39.5], [117.2008, 39.1252],
                        [117.16, 36.9], [117.1201, 36.6512]],
        fps=10,
    )
    result = render_map_route(
        table,
        tmp_path / "out",
        aspect="16:9",
        alignment=_alignment_for(table["stops"]),
        fetcher=_fake_tiles,
        capture_fn=_fake_capture,
    )
    mp4 = Path(result["mp4"])
    assert mp4.is_file() and mp4.stat().st_size > 0
    assert result["sidecar"]["timeline"]["mode"] == "alignment"
    assert result["sidecar"]["route"]["source"] == "shot-table-polyline"
    assert result["sidecar"]["basemap"]["source"] == "esri"
    probe = json.loads(
        __import__("subprocess").run(
            ["ffprobe", "-v", "quiet", "-show_format", "-of", "json", str(mp4)],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    assert float(probe["format"]["duration"]) > 3.0
    sidecar = Path(result["mp4"]).parent / "maproute_sidecar.json"
    assert sidecar.is_file()
    mp4.unlink()
    assert not mp4.exists(), "contract: deleting the artifact must break verification"
