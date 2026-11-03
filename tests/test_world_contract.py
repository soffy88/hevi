"""Tests for the spatial world contract package (hevi.world_contract).

Offline and dependency-free: formula evaluation, every validator rule,
the bundled river_vale examples (one compliant world + three deliberate
violation variants), the CLI exit codes, and capability registration.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hevi.world_contract import (
    ContractError,
    evaluate_formula,
    examples_dir,
    load_json,
    validate,
)

EX = examples_dir()
CONTRACT = load_json(EX / "river_vale.contract.json")
MANIFEST_OK = load_json(EX / "river_vale.manifest.ok.json")


def _rules(result) -> set[str]:
    return {v["rule"] for v in result["violations"]}


# ---------------------------------------------------------------------------
# Formula evaluation
# ---------------------------------------------------------------------------

def test_piecewise_linear_interpolates_and_clamps():
    f = {"id": "f", "kind": "piecewise_linear",
         "points": [[0, 0.9], [2, 0.62], [5, 0.4]]}
    assert evaluate_formula(f, 0) == pytest.approx(0.9)
    assert evaluate_formula(f, 2) == pytest.approx(0.62)
    assert evaluate_formula(f, 3.5) == pytest.approx(0.51)
    assert evaluate_formula(f, -10) == pytest.approx(0.9)   # clamped low
    assert evaluate_formula(f, 99) == pytest.approx(0.4)    # clamped high


def test_polynomial_horner():
    f = {"id": "g", "kind": "polynomial", "coeffs": [0.0, 4.8, -4.8]}
    assert evaluate_formula(f, 0.5) == pytest.approx(1.2)
    assert evaluate_formula(f, 0.0) == pytest.approx(0.0)


def test_formula_unknown_kind_raises():
    with pytest.raises(ContractError):
        evaluate_formula({"id": "x", "kind": "spline"}, 1.0)


# ---------------------------------------------------------------------------
# Compliant example
# ---------------------------------------------------------------------------

def test_example_world_passes():
    result = validate(CONTRACT, MANIFEST_OK)
    assert result["pass"], result["violations"]
    assert result["checked"]["objects"] == len(MANIFEST_OK["objects"])
    assert result["checked"]["interface_samples"] == len(
        MANIFEST_OK["interface_samples"])


def test_contract_only_passes():
    assert validate(CONTRACT)["pass"]


# ---------------------------------------------------------------------------
# Deliberate violation variants (bundled example files)
# ---------------------------------------------------------------------------

def test_bad_anchor_variant_is_reported():
    bad = load_json(EX / "river_vale.contract.bad_anchor.json")
    result = validate(bad, MANIFEST_OK)
    assert not result["pass"]
    hits = [v for v in result["violations"] if v["rule"] == "anchor_in_bounds"]
    assert hits and hits[0]["object"] == "wide_river_view"


def test_bad_zone_variant_is_reported_per_object():
    bad = load_json(EX / "river_vale.manifest.bad_zone.json")
    result = validate(CONTRACT, bad)
    assert not result["pass"]
    by_object = {(v["rule"], v["object"]) for v in result["violations"]}
    assert ("zone_rule_no_place", "rogue_shed") in by_object
    assert ("zone_rule_max_height", "signal_tower") in by_object


def test_bad_formula_variant_is_reported():
    bad = load_json(EX / "river_vale.manifest.bad_formula.json")
    result = validate(CONTRACT, bad)
    assert not result["pass"]
    hits = [v for v in result["violations"] if v["rule"] == "formula_interface"]
    assert len(hits) == 2  # side_b at h=2 and side_a at h=9 both disagree


# ---------------------------------------------------------------------------
# Individual rules, exercised by in-memory mutation
# ---------------------------------------------------------------------------

def test_missing_source_is_a_provenance_violation():
    manifest = copy.deepcopy(MANIFEST_OK)
    del manifest["objects"][0]["source"]
    result = validate(CONTRACT, manifest)
    assert "provenance" in _rules(result)


def test_hardcoded_coordinates_fail_provenance():
    # An object claiming an anchor source but sitting somewhere else is a
    # hand-written coordinate in disguise and must be rejected.
    manifest = copy.deepcopy(MANIFEST_OK)
    manifest["objects"][2]["position"] = [0, 3.4, 0]
    result = validate(CONTRACT, manifest)
    hits = [v for v in result["violations"]
            if v["rule"] == "provenance" and v["object"] == "bridge_deck"]
    assert hits


def test_unknown_zone_is_reported():
    manifest = copy.deepcopy(MANIFEST_OK)
    manifest["objects"][0]["zone"] = "nowhere"
    manifest["objects"][0]["source"] = {"type": "contract_range"}
    result = validate(CONTRACT, manifest)
    assert "zone_exists" in _rules(result)


def test_lighting_missing_field_is_reported():
    contract = copy.deepcopy(CONTRACT)
    del contract["lighting"]["timeline"][1]["night_factor"]
    result = validate(contract)
    assert "lighting_fields" in _rules(result)


def test_lighting_night_factor_out_of_range_is_reported():
    contract = copy.deepcopy(CONTRACT)
    contract["lighting"]["timeline"][0]["night_factor"] = 1.5
    result = validate(contract)
    assert "lighting_fields" in _rules(result)


def test_non_metric_units_are_rejected():
    contract = copy.deepcopy(CONTRACT)
    contract["world"]["units"] = "ft"
    result = validate(contract)
    assert "contract_fields" in _rules(result)


def test_absolute_time_convention_is_rejected():
    contract = copy.deepcopy(CONTRACT)
    contract["time"]["convention"] = "film_absolute"
    result = validate(contract)
    assert "contract_fields" in _rules(result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hevi.world_contract", *args],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )


def test_cli_validate_ok_exits_zero():
    proc = _run_cli("validate", str(EX / "river_vale.contract.json"),
                    str(EX / "river_vale.manifest.ok.json"))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["pass"] is True


def test_cli_validate_bad_zone_exits_one_and_reports():
    proc = _run_cli("validate", str(EX / "river_vale.contract.json"),
                    str(EX / "river_vale.manifest.bad_zone.json"))
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["pass"] is False
    assert len(report["violations"]) >= 2


def test_cli_check_contract_bad_anchor_exits_one():
    proc = _run_cli("check-contract",
                    str(EX / "river_vale.contract.bad_anchor.json"))
    assert proc.returncode == 1
    assert "anchor_in_bounds" in _rules(json.loads(proc.stdout))


# ---------------------------------------------------------------------------
# Capability registration (import-time self-registration precedent)
# ---------------------------------------------------------------------------

def test_capability_self_registers_on_import():
    import hevi.capabilities.world_contract  # noqa: F401
    from hevi.capabilities.registry import names

    assert "world.contract_validate" in names()


def test_capability_render_writes_report(tmp_path):
    import hevi.capabilities.world_contract  # noqa: F401
    from hevi.capabilities.registry import get

    result = get("world.contract_validate").render(
        {"contract_path": str(EX / "river_vale.contract.json"),
         "manifest_path": str(EX / "river_vale.manifest.ok.json")},
        tmp_path, duration=0, aspect="16:9", seed=1,
    )
    assert result.qa["pass"] is True
    report = json.loads(Path(result.qa["report_path"]).read_text("utf-8"))
    assert report["pass"] is True
