"""Tests for the Athenaion graft (clean-room, method only).

A1-A4: pure validators / session discipline, positive and
negative cases. B1-B5: browser renders are skipped when
Playwright/Chromium or the vendored three.js is unavailable
(same guard as the code-stage B4 tests); pure geometry/trace/
scatter checks always run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PIL import Image

from hevi.capabilities import get as _get_capability
from hevi.capabilities.athenaion_browser import _browser_available
from hevi.capabilities.athenaion_contract import (
    check_look_shot_plan,
    check_world_discipline,
    look_swap_delta,
)
from hevi.capabilities.athenaion_orders import (
    build_colonnade,
    build_column,
    build_entablature,
    shaft_radius,
)
from hevi.capabilities.athenaion_restoration import (
    check_restoration,
    color_stats,
    luminance_percentiles,
)
from hevi.capabilities.athenaion_session import WorldSession, check_session_record
from hevi.capabilities.athenaion_statue import build_statue, statue_sdf
from hevi.capabilities.athenaion_vegetation import plan_scatter, split_lod
from hevi.capabilities.athenaion_waterfall import build_ribbon, trace_stream
from hevi.capabilities.athenaion_world import height_at
from hevi.capabilities.errors import CapabilityError


def _good_plan() -> dict:
    return {
        "modules": [
            {"name": "terrain", "exports": ["build", "test"], "owner": "terrain", "ready": True, "ready_marker": "src/terrain/READY"},
            {"name": "trees", "exports": ["build", "test"], "owner": "trees"},
        ],
        "shared_files": [
            {"path": "src/world/layout.js", "owner": "terrain"},
            {"path": "src/world/shots.js", "owner": "director"},
        ],
        "edits": [{"path": "src/world/layout.js", "editor": "trees", "additive_only": True}],
        "coordination": {"footprints": True, "slots": True, "registry": True},
        "determinism": {
            "seeded_rng": True, "seed": 42,
            "sources": [{"path": "terrain.js", "text": "const r = engine.rng('terrain');"}],
        },
        "performance_budget": {
            "max_draw_calls": 500, "max_triangles": 1000000, "max_build_ms_per_module": 2000,
            "measured": {"draw_calls": 120, "triangles": 300000, "build_ms_per_module": {"terrain": 400}},
        },
    }


# ---------------------------------------------------------------- A1


def test_a1_good_plan_passes() -> None:
    report = check_world_discipline(_good_plan())
    assert report["verdict"] == "pass", report["issues"]
    assert report["issues"] == []


def test_a1_missing_test_export_fails() -> None:
    plan = _good_plan()
    plan["modules"][0]["exports"] = ["build"]
    assert any(i["code"] == "dual_export_missing" for i in check_world_discipline(plan)["issues"])


def test_a1_missing_coordination_fails() -> None:
    plan = _good_plan()
    del plan["coordination"]["slots"]
    assert any(i["code"] == "coordination_missing" for i in check_world_discipline(plan)["issues"])


def test_a1_non_owner_non_additive_edit_fails() -> None:
    plan = _good_plan()
    plan["edits"][0]["additive_only"] = False
    assert any(i["code"] == "shared_file_owner_violation" for i in check_world_discipline(plan)["issues"])


def test_a1_banned_source_fails() -> None:
    plan = _good_plan()
    plan["determinism"]["sources"] = [{"path": "x.js", "text": "const r = Math.random();"}]
    assert any(i["code"] == "banned_source" for i in check_world_discipline(plan)["issues"])
    plan["determinism"]["sources"][0]["text"] = "const t = Date.now();"
    assert any(i["code"] == "banned_source" for i in check_world_discipline(plan)["issues"])


def test_a1_missing_sources_fails() -> None:
    plan = _good_plan()
    del plan["determinism"]["sources"]
    assert any(i["code"] == "sources_missing" for i in check_world_discipline(plan)["issues"])


def test_a1_missing_budget_field_fails() -> None:
    plan = _good_plan()
    del plan["performance_budget"]["max_triangles"]
    assert any(i["code"] == "budget_field_missing" for i in check_world_discipline(plan)["issues"])


def test_a1_measured_over_budget_fails() -> None:
    plan = _good_plan()
    plan["performance_budget"]["measured"]["draw_calls"] = 9999
    assert any(i["code"] == "budget_exceeded" for i in check_world_discipline(plan)["issues"])


def test_a1_ready_without_marker_fails() -> None:
    plan = _good_plan()
    del plan["modules"][0]["ready_marker"]
    assert any(i["code"] == "ready_marker_missing" for i in check_world_discipline(plan)["issues"])


def test_a1_malformed_plan_raises() -> None:
    with pytest.raises(CapabilityError, match="JSON object"):
        check_world_discipline(None)


# ---------------------------------------------------------------- A2


def _good_look_shot() -> dict:
    return {
        "look": {
            "sun": {"elevation_deg": 25, "azimuth_deg": 135, "intensity": 2.2},
            "grade": {"exposure": 1.0, "saturation": 1.0},
            "fog": {"density": 0.004, "color_hex": "#c8d4e0"},
        },
        "shots": [
            {"name": "wide", "position": [55, 26, 62], "target": [0, 4, 0], "fov": 40, "movement": "static"},
        ],
    }


def test_a2_good_plan_passes() -> None:
    assert check_look_shot_plan(_good_look_shot())["verdict"] == "pass"


def test_a2_camera_field_in_look_fails() -> None:
    plan = _good_look_shot()
    plan["look"]["fov"] = 40
    assert any(i["code"] == "camera_field_in_look" for i in check_look_shot_plan(plan)["issues"])


def test_a2_look_field_in_shot_fails() -> None:
    plan = _good_look_shot()
    plan["shots"][0]["exposure"] = 1.2
    assert any(i["code"] == "look_field_in_shot" for i in check_look_shot_plan(plan)["issues"])


def test_a2_missing_shot_fov_fails() -> None:
    plan = _good_look_shot()
    del plan["shots"][0]["fov"]
    assert any(i["code"] == "shot_field_missing" for i in check_look_shot_plan(plan)["issues"])


def test_a2_missing_look_sun_fails() -> None:
    plan = _good_look_shot()
    del plan["look"]["sun"]
    assert any(i["code"] == "look_sun_missing" for i in check_look_shot_plan(plan)["issues"])


def test_a2_relative_sun_ok_and_mixed_fails() -> None:
    plan = _good_look_shot()
    plan["look"]["sun"] = {"relative": "left", "elevation_deg": 25}
    assert check_look_shot_plan(plan)["verdict"] == "pass"
    plan["look"]["sun"] = {"relative": "left", "azimuth_deg": 135}
    assert any(i["code"] == "sun_definition_mixed" for i in check_look_shot_plan(plan)["issues"])


def test_a2_look_swap_delta_separates_light_and_grade() -> None:
    a = {"sun_azimuth_deg": 135, "exposure": 1.0}
    b = {"sun_azimuth_deg": 45, "exposure": 1.0}
    delta = look_swap_delta(a, b)
    assert delta["light_changed"] == ["sun_azimuth_deg"]
    assert delta["grade_changed"] == []
    delta2 = look_swap_delta(a, {"sun_azimuth_deg": 135, "exposure": 1.4})
    assert delta2["light_changed"] == [] and delta2["grade_changed"] == ["exposure"]


# ---------------------------------------------------------------- A3


def _gradient_png(path: Path, width: int = 64, height: int = 32) -> Path:
    img = Image.new("RGB", (width, height))
    for x in range(width):
        value = round(255 * x / (width - 1))
        for y in range(height):
            img.putpixel((x, y), (value, value // 2, 255 - value))
    img.save(path)
    return path


def test_a3_percentiles_measured_not_defaulted(tmp_path: Path) -> None:
    path = _gradient_png(tmp_path / "ref.png")
    pct = luminance_percentiles(path)
    assert set(pct) == {"p02", "p10", "p50", "p90", "p98"}
    assert pct["p02"] < pct["p10"] < pct["p50"] < pct["p90"] < pct["p98"]
    stats = color_stats(path)
    assert stats["width"] == 64 and abs(stats["mean_r"] - stats["mean_b"]) < 2.0


def test_a3_matching_targets_pass(tmp_path: Path) -> None:
    ref = _gradient_png(tmp_path / "ref.png")
    ren = _gradient_png(tmp_path / "ren.png")
    pct = luminance_percentiles(ren)
    targets = {k: [v - 1.0, v + 1.0] for k, v in pct.items()}
    report = check_restoration(ref, ren, targets, out_cmp_path=tmp_path / "cmp.png")
    assert report["verdict"] == "pass", report["issues"]
    assert Path(report["comparison_path"]).is_file()


def test_a3_out_of_range_fails(tmp_path: Path) -> None:
    ref = _gradient_png(tmp_path / "ref.png")
    ren = _gradient_png(tmp_path / "ren.png")
    targets = {f"p{p:02d}": [250.0, 255.0] for p in (2, 10, 50, 90, 98)}
    report = check_restoration(ref, ren, targets)
    assert report["verdict"] == "fail"
    assert all(i["code"] == "percentile_out_of_range" for i in report["issues"])


def test_a3_missing_target_fails(tmp_path: Path) -> None:
    ref = _gradient_png(tmp_path / "ref.png")
    ren = _gradient_png(tmp_path / "ren.png")
    report = check_restoration(ref, ren, {"p50": [0.0, 255.0]})
    assert report["verdict"] == "fail"
    assert any(i["code"] == "target_missing" for i in report["issues"])


def test_a3_empty_targets_raise(tmp_path: Path) -> None:
    ref = _gradient_png(tmp_path / "ref.png")
    with pytest.raises(CapabilityError, match="targets"):
        check_restoration(ref, ref, {})


# ---------------------------------------------------------------- A4


def test_a4_session_builds_once_and_snaps(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    calls = {"n": 0}

    def build() -> dict:
        calls["n"] += 1
        time.sleep(0.02)
        return {"world": "test", "segments": 48}

    session = WorldSession(tmp_path, "world-1", build)
    session.variant("a", {"look": "warm"})
    session.variant("b", {"look": "cool"})
    session.variant("c", {"look": "dusk"})
    assert calls["n"] == 1
    assert session.build_calls == 1
    assert len(session.variants) == 3
    assert len({v["snapshot_id"] for v in session.variants}) == 3
    record = session.record(independent_build_ms=[20.0, 20.0, 20.0])
    report = check_session_record(record)
    assert report["verdict"] == "pass", report["issues"]
    assert report["variant_count"] == 3


def test_a4_rebuild_claim_fails() -> None:
    record = {
        "world_id": "w", "build": {"calls": 3, "build_hash": "abc", "build_ms": 10.0},
        "variants": [
            {"name": "a", "world_id": "w", "build_hash": "abc", "snapshot_id": "s1", "variant_ms": 1.0},
            {"name": "b", "world_id": "w", "build_hash": "abc", "snapshot_id": "s2", "variant_ms": 1.0},
        ],
        "variants_total_ms": 2.0, "independent_build_ms": [10.0, 10.0],
        "snapshot_ids": ["s1", "s2"],
    }
    assert any(i["code"] == "build_not_once" for i in check_session_record(record)["issues"])


def test_a4_unmeasured_economy_fails() -> None:
    record = {
        "world_id": "w", "build": {"calls": 1, "build_hash": "abc", "build_ms": 10.0},
        "variants": [
            {"name": "a", "world_id": "w", "build_hash": "abc", "snapshot_id": "s1", "variant_ms": 1.0},
            {"name": "b", "world_id": "w", "build_hash": "abc", "snapshot_id": "s2", "variant_ms": 1.0},
        ],
        "variants_total_ms": 2.0, "independent_build_ms": None,
        "snapshot_ids": ["s1", "s2"],
    }
    assert any(i["code"] == "independent_build_unmeasured" for i in check_session_record(record)["issues"])


def test_a4_hash_mismatch_fails() -> None:
    record = {
        "world_id": "w", "build": {"calls": 1, "build_hash": "abc", "build_ms": 10.0},
        "variants": [
            {"name": "a", "world_id": "w", "build_hash": "zzz", "snapshot_id": "s1", "variant_ms": 1.0},
            {"name": "b", "world_id": "w", "build_hash": "abc", "snapshot_id": "s2", "variant_ms": 1.0},
        ],
        "variants_total_ms": 2.0, "independent_build_ms": [10.0, 10.0],
        "snapshot_ids": ["s1", "s2"],
    }
    assert any(i["code"] == "variant_build_hash_mismatch" for i in check_session_record(record)["issues"])


# ---------------------------------------------------------------- B pure checks


def test_b1_heightfield_plateau_falls_east() -> None:
    assert height_at(-40, 0) > height_at(40, 0) + 3.0
    assert height_at(0, 0) == height_at(0, 0)


def test_b2_sdf_inside_outside() -> None:
    import numpy as np

    inside = statue_sdf(np.array([0.0]), np.array([3.28]), np.array([0.0]))[0]
    outside = statue_sdf(np.array([5.0]), np.array([3.28]), np.array([0.0]))[0]
    assert inside < 0 < outside


def test_b2_statue_mesh_has_triangles_and_normals() -> None:
    statue = build_statue(resolution=(28, 36, 28))
    assert statue["triangles"] > 100
    assert len(statue["mesh"]["normals"]) == len(statue["mesh"]["positions"]) > 0
    assert statue["build_ms"] > 0


def test_b3_orders_differ_and_entasis() -> None:
    doric = build_column("doric", diameter=1.0)
    ionic = build_column("ionic", diameter=1.0)
    assert ionic["total_height"] > doric["total_height"]
    assert ionic["shaft_height"] > doric["shaft_height"]
    # Entasis: radius swells above the base, then tapers to the top.
    r_base = shaft_radius("doric", 1.0, 0.05, doric["shaft_height"], 0.31)
    r_mid = shaft_radius("doric", 1.0, doric["shaft_height"] * 0.33, doric["shaft_height"], 0.31)
    r_top = shaft_radius("doric", 1.0, doric["shaft_height"] * 0.98, doric["shaft_height"], 0.31)
    assert r_mid > r_base > r_top or r_mid > r_top
    with pytest.raises(CapabilityError, match="unknown order"):
        build_column("tuscan")


def test_b3_entablature_and_footprints() -> None:
    ent = build_entablature("doric", bays=2)
    assert ent["triangles"] > 0 and ent["span"] > 0
    colonnade = build_colonnade("doric", count=3, spacing=3.0)
    assert colonnade["footprints_ok"] is True
    tight = build_colonnade("doric", count=3, spacing=0.5)
    assert tight["footprints_ok"] is False


def test_b4_trace_descends_and_tau_increases() -> None:
    trace = trace_stream((-14.0, 0.0))
    assert trace["point_count"] >= 4
    assert trace["drop_m"] >= 1.0
    assert trace["max_step_m"] <= 0.51
    ribbon = build_ribbon(trace)
    assert ribbon["tau_strictly_increasing"] is True
    assert ribbon["triangles"] > 0


def test_b4_flat_lip_fails() -> None:
    with pytest.raises(CapabilityError):
        trace_stream((40.0, 40.0), max_steps=4)


def test_b5_scatter_counts_and_avoidance() -> None:
    footprints = [{"x_min": -5.0, "x_max": 5.0, "z_min": -5.0, "z_max": 5.0}]
    plan = plan_scatter(count=300, seed=7, footprints=footprints)
    assert plan["placed"] == plan["planned"] == 300
    assert plan["rejected_by_footprints"] > 0
    for tree in plan["trees"]:
        assert not (-5.0 - 1.5 <= tree["x"] <= 5.0 + 1.5 and -5.0 - 1.5 <= tree["z"] <= 5.0 + 1.5)
    lod = split_lod(plan, (28.0, 18.0, 34.0))
    assert lod["total"] == 300 and lod["near_count"] > 0 and lod["far_count"] > 0


def test_b5_impossible_scatter_fails() -> None:
    footprints = [{"x_min": -100.0, "x_max": 100.0, "z_min": -100.0, "z_max": 100.0}]
    with pytest.raises(CapabilityError, match="placed"):
        plan_scatter(count=10, seed=1, footprints=footprints)


# ---------------------------------------------------------------- B browser renders


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b1_double_render_hash_identical(tmp_path: Path) -> None:
    from hevi.capabilities.athenaion_world import render_world

    report = render_world(
        out_dir=tmp_path, width=320, height=180, fps=10, duration_s=1.0,
        shot={"position": [55, 26, 62], "target": [0, 4, 0], "fov": 40, "movement": "static"},
    )
    assert report["verdict"] == "pass", report["issues"]
    assert report["hashes_identical"] is True
    assert report["triangles"] and report["triangles"] > 1000
    assert report["draw_calls"] and report["draw_calls"] >= 3


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b1_quality_high_more_triangles(tmp_path: Path) -> None:
    from hevi.capabilities.athenaion_world import render_world

    preview = render_world(out_dir=tmp_path / "p", width=320, height=180, fps=10, duration_s=0.1, quality="preview", runs=1)
    high = render_world(out_dir=tmp_path / "h", width=320, height=180, fps=10, duration_s=0.1, quality="high", runs=1)
    assert high["triangles"] > preview["triangles"]


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b3_colonnade_three_views(tmp_path: Path) -> None:
    from hevi.capabilities.athenaion_orders import render_colonnade

    report = render_colonnade(out_dir=tmp_path, width=320, height=180, order="ionic")
    assert report["verdict"] == "pass"
    assert report["footprints_ok"] is True
    assert [v["view"] for v in report["views"]] == ["front", "side", "top"]
    assert len({v["sha256"] for v in report["views"]}) == 3


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b2_statue_views_and_combined(tmp_path: Path) -> None:
    from hevi.capabilities.athenaion_statue import render_statue

    report = render_statue(out_dir=tmp_path, width=320, height=180, resolution=(28, 36, 28))
    assert report["verdict"] == "pass"
    assert report["triangles"] > 100
    assert [v["view"] for v in report["views"]] == ["front", "side", "top", "combined"]


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b5_vegetation_counts_and_draw_calls(tmp_path: Path) -> None:
    from hevi.capabilities.athenaion_vegetation import render_vegetation

    report = render_vegetation(out_dir=tmp_path, width=320, height=180, count=300, seed=3)
    assert report["counts_match"] is True
    assert report["placed"] == 300
    assert report["draw_calls"] is not None and report["draw_calls"] <= 12
    assert [v["view"] for v in report["views"]] == ["overview", "closeup"]


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b4_waterfall_short_sequence_flows(tmp_path: Path) -> None:
    from hevi.capabilities.athenaion_waterfall import render_waterfall

    report = render_waterfall(out_dir=tmp_path, width=320, height=180, fps=10, duration_s=2.0, assemble_video=False)
    assert report["verdict"] == "pass", report["issues"]
    assert report["frames_flow"] is True
    assert report["distinct_frame_hashes"] > 1


# ---------------------------------------------------------------- registry


def test_athenaion_capabilities_registered(tmp_path: Path) -> None:
    for name in (
        "world.athenaion_discipline",
        "qa.look_shot_separation",
        "qa.reference_restoration_gate",
        "pipeline.athenaion_session",
        "video.athenaion_world_engine",
        "world.athenaion_sdf_statue",
        "world.athenaion_classical_orders",
        "video.athenaion_waterfall",
        "world.athenaion_vegetation_scatter",
    ):
        assert _get_capability(name).name == name


def test_athenaion_report_modes(tmp_path: Path) -> None:
    cap = _get_capability("world.athenaion_discipline")
    result = cap.render_safe(
        {"plan": _good_plan()}, tmp_path / "a1", duration=0.0, aspect="16:9", seed=0,
    )
    assert result.qa["ok"] is True
    cap2 = _get_capability("qa.look_shot_separation")
    result2 = cap2.render_safe(
        {"mode": "look_shot", "plan": _good_look_shot()}, tmp_path / "a2", duration=0.0, aspect="16:9", seed=0,
    )
    assert result2.qa["ok"] is True
    report = json.loads(Path(result2.qa["report_json"]).read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
