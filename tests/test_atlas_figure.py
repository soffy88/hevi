"""Tests for the atlas-figure capability (physics figure scene specs).

Pure stdlib/spec tests: no chromium, no ffmpeg, no network.  The reference
figures are the module's own self-written specs; every mutation below starts
from a deepcopy of one of them, so a failure proves the gate itself.
"""

from __future__ import annotations

import copy
import json

import pytest

from hevi.capabilities import CapabilityError, get
from hevi.capabilities.atlas_figure import (
    CAPABILITY_NAME,
    FigureSpecError,
    _eval_expr,
    generate_scene,
    reference_figures,
    register_atlas_figure_capabilities_once,
    run_checks,
    scene_to_json,
    verify_figure_spec,
)
from hevi.capabilities.registry import describe


@pytest.fixture(params=["projectile", "pendulum"])
def spec(request):
    return copy.deepcopy(reference_figures()[request.param])


def _mutate(spec, fn):
    mutated = copy.deepcopy(spec)
    fn(mutated)
    return mutated


def test_reference_figures_verify_and_pass(spec):
    verification = verify_figure_spec(spec)
    assert verification.ok, verification.reasons
    report = run_checks(spec)
    assert report.all_passed
    assert len(report.outcomes) == len(spec["checks"])
    scene = generate_scene(spec)
    assert scene["schema_version"] == 1
    assert scene["id"] == spec["id"]
    assert scene["checks"]["all_passed"] is True


def test_verify_rejects_missing_caveat(spec):
    bad = _mutate(spec, lambda s: s["model"].update(caveat=""))
    assert not verify_figure_spec(bad).ok


def test_verify_rejects_short_caveat(spec):
    bad = _mutate(spec, lambda s: s["model"].update(caveat="no air"))
    assert not verify_figure_spec(bad).ok


def test_verify_rejects_camera_page_gap(spec):
    def _gap(s):
        s["cameras"][1]["page"] = 2

    assert not verify_figure_spec(_mutate(spec, _gap)).ok


def test_verify_rejects_camera_el_out_of_range(spec):
    def _el(s):
        s["cameras"][0]["el"] = 90.0

    assert not verify_figure_spec(_mutate(spec, _el)).ok


def test_verify_rejects_camera_az_out_of_range(spec):
    def _az(s):
        s["cameras"][0]["az"] = 200.0

    assert not verify_figure_spec(_mutate(spec, _az)).ok


def test_verify_rejects_dangling_breakdown_target(spec):
    def _target(s):
        s["breakdowns"][0]["target"] = "no-such-assembly"

    assert not verify_figure_spec(_mutate(spec, _target)).ok


def test_verify_rejects_breakdown_kind_mismatch(spec):
    def _kind(s):
        s["breakdowns"][0]["kind"] = "graph_slope_area"
        s["breakdowns"][0]["target"] = (
            "frame" if "frame" in {a["id"] for a in s["scene"]["assemblies"]} else "pendulum"
        )

    assert not verify_figure_spec(_mutate(spec, _kind)).ok


def test_verify_rejects_fewer_than_two_checks(spec):
    def _one(s):
        s["checks"] = s["checks"][:1]

    assert not verify_figure_spec(_mutate(spec, _one)).ok


def test_verify_rejects_no_independent_recompute(spec):
    def _closed(s):
        for check in s["checks"]:
            check["path_b"] = {"method": "closed_form", "expression": "1"}

    assert not verify_figure_spec(_mutate(spec, _closed)).ok


def test_verify_rejects_same_method_twice(spec):
    def _same(s):
        s["checks"][0]["path_b"] = dict(s["checks"][0]["path_a"])

    assert not verify_figure_spec(_mutate(spec, _same)).ok


def test_verify_rejects_undeclared_quantity_ref(spec):
    def _ref(s):
        s["breakdowns"][0]["facts"][0]["quantity"] = "not_a_quantity"

    assert not verify_figure_spec(_mutate(spec, _ref)).ok


def test_verify_rejects_derived_value_mismatch(spec):
    def _value(s):
        s["model"]["derived"][0]["value"] += 0.5

    verification = verify_figure_spec(_mutate(spec, _value))
    assert not verification.ok
    assert any("does not match formula" in r for r in verification.reasons)


def test_verify_rejects_unsafe_expressions(spec):
    for bad_expr in (
        "__import__('os').system('id')",
        "os.path.join('a', 'b')",
        "[1, 2, 3][0]",
        "(lambda t: t)(1)",
        "t if t > 0 else 0",
    ):

        def _expr(s, expr=bad_expr):
            s["model"]["functions"][0]["expression"] = expr

        assert not verify_figure_spec(_mutate(spec, _expr)).ok, bad_expr


def test_verify_rejects_unknown_material(spec):
    def _mat(s):
        s["scene"]["parts"][0]["material"]["palette"] = "neon"

    assert not verify_figure_spec(_mutate(spec, _mat)).ok


def test_verify_rejects_dangling_graph_function(spec):
    def _fn(s):
        for part in s["scene"]["parts"]:
            if part["kind"] == "graph":
                part["function"] = "no_such_function"

    assert not verify_figure_spec(_mutate(spec, _fn)).ok


def test_safe_evaluator_allows_whitelisted_math():
    env = {"t": 0.5, "g": 9.8, "pi": 3.141592653589793}
    assert _eval_expr("sqrt(g*t*t + 1)", env) == pytest.approx(1.8574, rel=1e-3)
    assert _eval_expr("hypot(3, 4)", env) == 5.0
    assert _eval_expr("sin(pi/2)", env) == pytest.approx(1.0)
    with pytest.raises(FigureSpecError):
        _eval_expr("open('x').read()", env)
    with pytest.raises(FigureSpecError):
        _eval_expr("t.__class__", env)


def test_run_checks_reports_tolerance_failure(spec):
    def _tight(s):
        # Shift path_a by a fixed 0.01 so the two recomputations genuinely disagree.
        s["checks"][0]["path_a"]["expression"] += " + 0.01"

    mutated = _mutate(spec, _tight)
    assert verify_figure_spec(mutated).ok
    report = run_checks(mutated)
    assert not report.all_passed
    assert any(not o.passed for o in report.outcomes)
    with pytest.raises(FigureSpecError, match="invariant checks failed"):
        generate_scene(mutated)


def test_run_checks_bisection_without_sign_change_reports_error(spec):
    pendulum = reference_figures()["pendulum"]
    bad = copy.deepcopy(pendulum)
    bad["checks"][0]["path_b"]["lo"] = 0.1
    bad["checks"][0]["path_b"]["hi"] = 0.2
    assert verify_figure_spec(bad).ok
    report = run_checks(bad)
    assert not report.all_passed
    failed = [o for o in report.outcomes if not o.passed]
    assert failed and "sign change" in failed[0].error


def test_generate_scene_is_byte_deterministic(spec):
    first = scene_to_json(generate_scene(spec))
    second = scene_to_json(generate_scene(spec))
    assert first == second
    # The seed is recorded in meta, so a different seed differs only there.
    assert generate_scene(spec, seed=7)["meta"]["seed"] == 7
    scene = json.loads(first)
    assert scene["parts"] and scene["cameras"] and scene["breakdowns"]
    assert scene["meta"]["deterministic"] is True


def test_generate_scene_rejects_invalid_spec(spec):
    bad = _mutate(spec, lambda s: s["model"].update(caveat=""))
    with pytest.raises(FigureSpecError, match="failed verification"):
        generate_scene(bad)


def test_generate_scene_resolves_graph_and_strobe(spec):
    scene = generate_scene(reference_figures()["projectile"])
    by_id = {p["id"]: p for p in scene["parts"]}
    graph = by_id["yt-graph"]["graph"]
    assert len(graph["points"]) == 50
    assert graph["points"][0][1] == pytest.approx(5.0)
    assert graph["slope_at_mid"] < 0  # height falls as time passes
    assert graph["area_under_curve"] > 0
    strobe = by_id["strobe"]["strobe"]
    assert strobe["points"][0]["position"] == [0.0, 5.0, 0.0]
    assert strobe["points"][-1]["position"][0] == pytest.approx(8.0)


def test_generate_scene_resolves_materials(spec):
    scene = generate_scene(spec)
    for part in scene["parts"]:
        material = part["material"]
        assert len(material["tones"]) == 3
        assert 0.0 < material["tone_weight"] <= 1.0
        assert 0.0 < material["opacity"] <= 1.0


def test_registry_wiring_is_idempotent():
    first = register_atlas_figure_capabilities_once()
    second = register_atlas_figure_capabilities_once()
    assert first[0] is second[0]
    cap = get(CAPABILITY_NAME)
    assert cap.kind == "line"
    assert "16:9" in cap.aspects
    assert any(entry["name"] == CAPABILITY_NAME for entry in describe())


def test_registry_render_writes_deterministic_scene_json(tmp_path):
    cap = get(CAPABILITY_NAME)
    spec = reference_figures()["projectile"]
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    result_a = cap.render({"spec": spec}, str(out_a), duration=3.0, aspect="16:9", seed=0)
    result_b = cap.render({"spec": spec}, str(out_b), duration=3.0, aspect="16:9", seed=0)
    assert result_a.sha256 == result_b.sha256
    scene = json.loads((out_a / "atlas_figure_scene.json").read_text(encoding="utf-8"))
    assert scene["id"] == "reference-projectile"
    assert scene["checks"]["all_passed"] is True
    checks = json.loads((out_a / "atlas_figure_checks.json").read_text(encoding="utf-8"))
    assert checks["all_passed"] is True
    assert result_a.qa["figure_id"] == "reference-projectile"
    assert result_a.qa["media"] is None


def test_registry_render_rejects_invalid_spec(tmp_path):
    cap = get(CAPABILITY_NAME)
    bad = copy.deepcopy(reference_figures()["projectile"])
    bad["model"]["caveat"] = ""
    with pytest.raises(CapabilityError, match="spec rejected"):
        cap.render({"spec": bad}, str(tmp_path), duration=1.0, aspect="16:9", seed=0)
