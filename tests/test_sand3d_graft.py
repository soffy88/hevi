"""Tests for the sand3d graft.

Every capability gets a positive case and at least one
negative case. The registration test asserts all twelve
names are present exactly once. The schema (B) tests assert
fail-closed behaviour: ``compile_*`` returns a contract
declaring ``executed_here`` false and ``output_file`` None on
a well-formed input, and raises ``CapabilityError`` on any
shape violation. No test runs Blender or any sand3d code.
"""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.sand3d_dataset_attribution_gate import (
    check_sand3d_dataset_attribution,
)
from hevi.capabilities.sand3d_dataset_card_schema import (
    compile_sand3d_dataset_card,
)
from hevi.capabilities.sand3d_determinism_gate import check_sand3d_determinism
from hevi.capabilities.sand3d_export_format_gate import check_sand3d_export_format
from hevi.capabilities.sand3d_export_schema import compile_sand3d_export
from hevi.capabilities.sand3d_ifc_export_schema import compile_sand3d_ifc_export
from hevi.capabilities.sand3d_ifc_honesty_gate import check_sand3d_ifc_honesty
from hevi.capabilities.sand3d_joint_gate import check_sand3d_joint
from hevi.capabilities.sand3d_modeling_vocabulary_gate import (
    check_sand3d_modeling_vocabulary,
)
from hevi.capabilities.sand3d_program_schema import compile_sand3d_program
from hevi.capabilities.sand3d_prompt_pack_gate import check_sand3d_prompt_pack
from hevi.capabilities.sand3d_urdf_joint_schema import compile_sand3d_urdf_joint

EXPECTED_SAND3D_NAMES = {
    "qa.sand3d_modeling_vocabulary_gate",
    "qa.sand3d_export_format_gate",
    "qa.sand3d_joint_gate",
    "qa.sand3d_prompt_pack_gate",
    "qa.sand3d_determinism_gate",
    "qa.sand3d_ifc_honesty_gate",
    "qa.sand3d_dataset_attribution_gate",
    "model.sand3d_program_schema",
    "model.sand3d_export_schema",
    "model.sand3d_urdf_joint_schema",
    "model.sand3d_ifc_export_schema",
    "model.sand3d_dataset_card_schema",
}


def _good_program() -> dict:
    return {
        "verbs": ["rect", "extrude", "fillet"],
        "units": "mm",
        "uses_named_selection": True,
        "selects_edges_or_faces": True,
    }


def test_vocabulary_pass():
    report = check_sand3d_modeling_vocabulary(_good_program())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_vocabulary_rejects_category_verb():
    program = _good_program()
    program["verbs"] = ["rect", "chair"]
    report = check_sand3d_modeling_vocabulary(program)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "unknown_verb"


def test_vocabulary_rejects_no_shape_verb():
    program = _good_program()
    program["verbs"] = ["fillet", "copy"]
    report = check_sand3d_modeling_vocabulary(program)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "no_shape_verb"


def test_vocabulary_rejects_geometric_selector():
    program = _good_program()
    program["uses_geometric_selector"] = True
    report = check_sand3d_modeling_vocabulary(program)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "geometric_selector_banned"


def test_vocabulary_rejects_missing_units():
    program = _good_program()
    del program["units"]
    report = check_sand3d_modeling_vocabulary(program)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "units_missing"


def test_export_format_pass():
    exports = [
        {"path": "part.glb"},
        {"path": "part.urdf"},
        {"path": "part.usda"},
        {"path": "part.ifc"},
        {"path": "part.obj"},
        {"path": "part.stl"},
    ]
    assert check_sand3d_export_format(exports)["verdict"] == "pass"


def test_export_format_rejects_usd_binary():
    report = check_sand3d_export_format([{"path": "part.usd"}])
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "usd_binary_rejected"


def test_export_format_rejects_revit():
    report = check_sand3d_export_format([{"path": "part.rvt"}])
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "revit_format_rejected"


def test_export_format_rejects_unknown_suffix():
    report = check_sand3d_export_format([{"path": "part.xyz"}])
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "unsupported_format"


def test_export_format_rejects_no_extension():
    report = check_sand3d_export_format([{"path": "part"}])
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "export_no_extension"


def _good_joints() -> list:
    return [
        {
            "name": "door_hinge",
            "child": "door",
            "on": "body",
            "kind": "revolute",
            "axis": "normal",
            "range": [0, 143],
        },
        {
            "name": "drum_spin",
            "child": "drum",
            "on": "body",
            "kind": "continuous",
            "axis": "normal",
        },
        {
            "name": "drawer_slide",
            "child": "drawer",
            "on": "body",
            "kind": "prismatic",
            "axis": "normal",
            "range": [0, 120],
        },
        {
            "name": "dial_turn",
            "child": "dial",
            "on": "body",
            "kind": "revolute",
            "axis": "normal",
            "range": [0, 270],
        },
    ]


def test_joint_pass():
    assert check_sand3d_joint(_good_joints())["verdict"] == "pass"


def test_joint_rejects_ranged_without_range():
    joints = _good_joints()
    del joints[0]["range"]
    report = check_sand3d_joint(joints)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "joint_range_missing"


def test_joint_rejects_range_on_endless():
    joints = _good_joints()
    joints[1]["range"] = [0, 360]
    report = check_sand3d_joint(joints)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "joint_range_forbidden"


def test_joint_rejects_unknown_kind():
    joints = _good_joints()
    joints[0]["kind"] = "ball"
    report = check_sand3d_joint(joints)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "joint_kind_unknown"


def test_joint_rejects_inverted_range():
    joints = _good_joints()
    joints[0]["range"] = [143, 0]
    report = check_sand3d_joint(joints)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "joint_range_inverted"


def _good_pack() -> dict:
    return {
        "sand3d_version": "1.6.3",
        "api_doc_words": 1818,
        "estimated_tokens": 2700,
        "token_budget": 4000,
    }


def test_prompt_pack_pass():
    assert check_sand3d_prompt_pack(_good_pack())["verdict"] == "pass"


def test_prompt_pack_rejects_unpinned_version():
    pack = _good_pack()
    pack["sand3d_version"] = "1.6.2"
    report = check_sand3d_prompt_pack(pack)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "version_not_pinned"


def test_prompt_pack_rejects_unmeasured_estimate():
    pack = _good_pack()
    pack["estimated_tokens"] = 4000
    report = check_sand3d_prompt_pack(pack)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "token_estimate_unmeasured"


def test_prompt_pack_rejects_budget_exceeded():
    pack = _good_pack()
    pack["estimated_tokens"] = 3000
    pack["token_budget"] = 2500
    report = check_sand3d_prompt_pack(pack)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "token_budget_exceeded"


def test_prompt_pack_rejects_unmeasured_reduction_claim():
    pack = _good_pack()
    pack["claimed_token_reduction"] = 4.0
    report = check_sand3d_prompt_pack(pack)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "reduction_unmeasured"


def _good_determinism() -> dict:
    return {
        "scope": "program_to_mesh_digest",
        "runs": [
            {"hash_seed": "0", "digest": "abc"},
            {"hash_seed": "1", "digest": "abc"},
        ],
        "golden_digest": "abc",
    }


def test_determinism_pass():
    assert check_sand3d_determinism(_good_determinism())["verdict"] == "pass"


def test_determinism_rejects_drift():
    report = _good_determinism()
    report["runs"][1]["digest"] = "abd"
    result = check_sand3d_determinism(report)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "digest_drift"


def test_determinism_rejects_repeated_seed():
    report = _good_determinism()
    report["runs"][1]["hash_seed"] = "0"
    result = check_sand3d_determinism(report)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "hash_seed_repeated"


def test_determinism_rejects_byte_identical_overclaim():
    report = _good_determinism()
    report["scope"] = "byte_identical_exports"
    result = check_sand3d_determinism(report)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "scope_overclaim"


def test_determinism_rejects_golden_mismatch():
    report = _good_determinism()
    report["golden_digest"] = "zzz"
    result = check_sand3d_determinism(report)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "golden_mismatch"


def _good_ifc() -> dict:
    return {
        "format": "ifc",
        "states_global_id_unstable": True,
        "global_id_notice": ("GlobalIds may change on edit; do not track parts across exports."),
        "excluded_quantities": ["mass", "inertia", "dynamics"],
    }


def test_ifc_honesty_pass():
    assert check_sand3d_ifc_honesty(_good_ifc())["verdict"] == "pass"


def test_ifc_honesty_rejects_unstated_instability():
    export = _good_ifc()
    export["states_global_id_unstable"] = False
    report = check_sand3d_ifc_honesty(export)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "global_id_stability_unstated"


def test_ifc_honesty_rejects_missing_notice():
    export = _good_ifc()
    del export["global_id_notice"]
    report = check_sand3d_ifc_honesty(export)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "global_id_notice_missing"


def test_ifc_honesty_rejects_incomplete_exclusions():
    export = _good_ifc()
    export["excluded_quantities"] = ["color"]
    report = check_sand3d_ifc_honesty(export)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "excluded_quantities_incomplete"


def _good_datasets() -> list:
    return [
        {
            "name": "objaverse",
            "license": "CC BY 4.0",
            "attribution": "Objaverse, CC BY 4.0",
            "source_chain": ["objaverse"],
        }
    ]


def test_dataset_attribution_pass():
    assert check_sand3d_dataset_attribution(_good_datasets())["verdict"] == "pass"


def test_dataset_attribution_rejects_unknown_dataset():
    datasets = _good_datasets()
    datasets[0]["name"] = "thingiverse"
    report = check_sand3d_dataset_attribution(datasets)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "unknown_dataset"


def test_dataset_attribution_rejects_wrong_license():
    datasets = _good_datasets()
    datasets[0]["license"] = "MIT"
    report = check_sand3d_dataset_attribution(datasets)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "license_mismatch"


def test_dataset_attribution_rejects_missing_attribution():
    datasets = _good_datasets()
    del datasets[0]["attribution"]
    report = check_sand3d_dataset_attribution(datasets)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "attribution_missing"


def test_dataset_attribution_rejects_hevi_asset_claim():
    datasets = _good_datasets()
    datasets[0]["meshes_are_hevi_assets"] = True
    report = check_sand3d_dataset_attribution(datasets)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "meshes_claimed_as_hevi_assets"


def test_program_schema_pass():
    contract = compile_sand3d_program(
        {
            "program_id": "bracket",
            "sand3d_version": "1.6.3",
            "units": "mm",
            "verbs": ["rect", "extrude"],
            "parts": [{"part_id": "base", "verbs": ["rect", "extrude"]}],
        }
    )
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["verb_count"] == 2
    assert contract["part_count"] == 1


def test_program_schema_rejects_unpinned_version():
    with pytest.raises(CapabilityError):
        compile_sand3d_program(
            {
                "program_id": "bracket",
                "sand3d_version": "1.6.2",
                "units": "mm",
                "verbs": ["rect", "extrude"],
            }
        )


def test_program_schema_rejects_category_verb():
    with pytest.raises(CapabilityError):
        compile_sand3d_program(
            {
                "program_id": "bracket",
                "sand3d_version": "1.6.3",
                "units": "mm",
                "verbs": ["rect", "chair"],
            }
        )


def test_program_schema_rejects_missing_id():
    with pytest.raises(CapabilityError):
        compile_sand3d_program({"sand3d_version": "1.6.3", "units": "mm", "verbs": ["rect"]})


def test_export_schema_pass():
    contract = compile_sand3d_export(
        {
            "program_id": "bracket",
            "exports": [{"path": "bracket.glb"}, {"path": "bracket.usda"}],
        }
    )
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["formats"] == [".glb", ".usda"]


def test_export_schema_rejects_usd_binary():
    with pytest.raises(CapabilityError):
        compile_sand3d_export({"program_id": "bracket", "exports": [{"path": "bracket.usd"}]})


def _good_urdf() -> dict:
    return {
        "program_id": "washer",
        "links": [{"name": "body"}, {"name": "door"}, {"name": "drum"}],
        "joints": [
            {
                "name": "door_hinge",
                "child": "door",
                "on": "body",
                "kind": "revolute",
                "axis": "normal",
                "range": [0, 143],
            },
            {
                "name": "drum_spin",
                "child": "drum",
                "on": "body",
                "kind": "continuous",
                "axis": "normal",
            },
        ],
    }


def test_urdf_joint_schema_pass():
    contract = compile_sand3d_urdf_joint(_good_urdf())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["link_count"] == 3
    assert contract["joint_count"] == 2


def test_urdf_joint_schema_rejects_undeclared_link():
    urdf = _good_urdf()
    urdf["joints"][0]["child"] = "lid"
    with pytest.raises(CapabilityError):
        compile_sand3d_urdf_joint(urdf)


def _good_ifc_export() -> dict:
    return {
        "program_id": "bracket",
        "ifc_version": "IFC4",
        "project": "demo",
        "parts": [{"part_id": "base"}],
        "global_id_notice": ("GlobalIds may change on edit; do not track parts across exports."),
        "states_global_id_unstable": True,
        "excluded_quantities": ["mass"],
    }


def test_ifc_export_schema_pass():
    contract = compile_sand3d_ifc_export(_good_ifc_export())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["part_count"] == 1


def test_ifc_export_schema_rejects_wrong_version():
    ifc = _good_ifc_export()
    ifc["ifc_version"] = "IFC2x3"
    with pytest.raises(CapabilityError):
        compile_sand3d_ifc_export(ifc)


def test_ifc_export_schema_rejects_missing_notice():
    ifc = _good_ifc_export()
    del ifc["global_id_notice"]
    with pytest.raises(CapabilityError):
        compile_sand3d_ifc_export(ifc)


def test_dataset_card_schema_pass():
    contract = compile_sand3d_dataset_card(
        {
            "dataset": "cad",
            "license": "CC BY 4.0",
            "attribution": "Zero-To-CAD, CC BY 4.0",
            "source_chain": ["zero-to-cad"],
            "program_pointer": "programs/cad/bracket.py",
        }
    )
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["dataset"] == "cad"


def test_dataset_card_schema_rejects_unknown_dataset():
    with pytest.raises(CapabilityError):
        compile_sand3d_dataset_card(
            {
                "dataset": "thingiverse",
                "license": "CC BY 4.0",
                "attribution": "x",
                "source_chain": ["thingiverse"],
                "program_pointer": "programs/x.py",
            }
        )


def test_dataset_card_schema_rejects_hevi_asset_claim():
    with pytest.raises(CapabilityError):
        compile_sand3d_dataset_card(
            {
                "dataset": "cad",
                "license": "CC BY 4.0",
                "attribution": "Zero-To-CAD, CC BY 4.0",
                "source_chain": ["zero-to-cad"],
                "program_pointer": "programs/cad/bracket.py",
                "meshes_are_hevi_assets": True,
            }
        )


def test_sand3d_graft_registered_once():
    from hevi.capabilities import list_capabilities

    found = [c.name for c in list_capabilities() if c.name in EXPECTED_SAND3D_NAMES]
    assert sorted(found) == sorted(EXPECTED_SAND3D_NAMES)
    assert len(found) == 12
