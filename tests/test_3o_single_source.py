"""Single-source guard tests (HELIOS_3O_SPEC_v3_0 section 1.4).

Each test locks a convergence verdict from 3O_CONFORMANCE.md section 4:
one implementation per logic, the rest delegating aliases, with
bitwise-identical behaviour asserted on the same inputs.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from hevi.capabilities import get as caps_get
from hevi.capabilities import list_capabilities
from hevi.capabilities.registry import overwrite_history

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- pricing ---
def test_pricing_record_single_source(tmp_path: Path) -> None:
    """Floyo/Modal record writers and the shared writer agree bitwise."""
    from hevi.capabilities.floyo_h3_registration import (
        FLOYO_MODEL_ID,
        LOCAL_H3_MODEL_ID,
        floyo_h3_config,
        local_h3_config,
        record_in_directory as floyo_record,
        validate_floyo_config,
    )
    from hevi.capabilities.modal_pricing_registration import (
        MODAL_MODEL_ID,
        modal_pricing_config,
        record_in_directory as modal_record,
        validate_modal_config,
    )
    from hevi.capabilities.model_directory import (
        record_in_directory as shared_record,
    )

    dir_a = tmp_path / "a.json"
    dir_b = tmp_path / "b.json"
    floyo_record(dir_a)
    modal_record(dir_a)
    shared_record(
        dir_b,
        {
            FLOYO_MODEL_ID: validate_floyo_config(floyo_h3_config()),
            LOCAL_H3_MODEL_ID: dict(local_h3_config()),
            MODAL_MODEL_ID: validate_modal_config(modal_pricing_config()),
        },
    )
    data_a = json.loads(dir_a.read_text(encoding="utf-8"))
    data_b = json.loads(dir_b.read_text(encoding="utf-8"))
    assert data_a == data_b
    for record in data_a["models"].values():
        assert record["status"] == "unverified"
        assert record["verified_at"] is None


def test_seedance_vidogrid_single_source(tmp_path: Path) -> None:
    """Record writes exactly one unverified record; describe writes nothing."""
    for name, model_id in (
        ("model.seedance_pricing_registration", "doubao-seedance-2.5-260628"),
        ("model.vidogrid_pricing_registration", "vidogrid"),
    ):
        cap = caps_get(name)
        directory = tmp_path / f"{model_id}.json"
        out = tmp_path / f"out-{model_id}"
        out.mkdir(parents=True, exist_ok=True)
        result = cap.render_safe(
            {"action": "record", "directory_path": str(directory)},
            out, duration=0.0, aspect="16:9", seed=1,
        )
        assert result.qa["verdict"] == "pass"
        data = json.loads(directory.read_text(encoding="utf-8"))
        assert set(data["models"]) == {model_id}
        assert data["models"][model_id]["status"] == "unverified"
        # Describe must not touch the directory.
        directory2 = tmp_path / f"{model_id}-describe.json"
        out2 = tmp_path / f"out2-{model_id}"
        out2.mkdir(parents=True, exist_ok=True)
        cap.render_safe(
            {"action": "describe", "directory_path": str(directory2)},
            out2, duration=0.0, aspect="16:9", seed=1,
        )
        assert not directory2.exists()


def test_h3_config_single_source() -> None:
    """Floyo local route delegates H3 config values to config_record()."""
    from hevi.capabilities.floyo_h3_registration import local_h3_config
    from hevi.capabilities.h3_config_registration import config_record

    canonical = config_record()
    local = local_h3_config()
    for key in (
        "config_id", "components", "source", "source_date", "verification",
        "not_equivalent_to", "incompatible_lora_families", "weight_license",
    ):
        assert local["h3_config"][key] == canonical[key]
    assert local["verified"] == canonical["verified"]
    shared = set(local) & set(canonical)
    for key in shared:
        assert local[key] == canonical[key], key


def test_pricing_single_source(tmp_path: Path) -> None:
    """Execution pricing and directory records share no model key today.

    The test locks the empty intersection so any future overlap is
    caught automatically, and asserts every directory record carries
    a verified/unverified status marker.
    """
    from hevi.capabilities.model_directory import get_record
    from hevi.capabilities.floyo_h3_registration import record_in_directory as floyo_record
    from hevi.capabilities.modal_pricing_registration import record_in_directory as modal_record
    from hevi.cost.pricing_table import get_pricing_table

    directory = tmp_path / "directory.json"
    floyo_record(directory)
    modal_record(directory)
    for name in ("model.seedance_pricing_registration",
                 "model.vidogrid_pricing_registration"):
        out_dir = tmp_path / f"out-{name}"
        out_dir.mkdir(parents=True, exist_ok=True)
        caps_get(name).render_safe(
            {"action": "record", "directory_path": str(directory)},
            out_dir, duration=0.0, aspect="16:9", seed=1,
        )
    data = json.loads(directory.read_text(encoding="utf-8"))
    model_ids = set(data["models"])
    pricing_keys = set(get_pricing_table())
    overlap = model_ids & pricing_keys
    assert overlap == set()
    for key in overlap:  # vacuous today; binds the day overlap appears
        assert data["models"][key]["config"] == get_pricing_table()[key]
    for model_id in model_ids:
        record = get_record(directory, model_id)
        assert record["status"] in ("unverified", "verified")


# ------------------------------------------------------------- athenaion ---
def test_athenaion_single_source(tmp_path: Path) -> None:
    """look_shot alias output == discipline output with mode=look_shot."""
    plan = {
        "look": {"light": "soft", "grade": "warm"},
        "shots": [{"camera": "static", "movement": "none"}],
    }
    out_alias = tmp_path / "alias"
    out_canon = tmp_path / "canon"
    report_alias = caps_get("qa.look_shot_separation").render_safe(
        {"mode": "look_shot", "plan": plan}, out_alias,
        duration=0.0, aspect="16:9", seed=1,
    )
    report_canon = caps_get("world.athenaion_discipline").render_safe(
        {"mode": "look_shot", "plan": plan}, out_canon,
        duration=0.0, aspect="16:9", seed=1,
    )
    alias_json = json.loads(
        Path(report_alias.qa["report_json"]).read_text(encoding="utf-8"))
    canon_json = json.loads(
        Path(report_canon.qa["report_json"]).read_text(encoding="utf-8"))
    assert alias_json == canon_json
    # check_look_shot_plan has exactly one definition in the repo.
    source = (REPO_ROOT / "hevi/capabilities/athenaion_contract.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    defs = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "check_look_shot_plan"]
    assert len(defs) == 1


# ------------------------------------------------------------------ riso ---
def test_riso_single_registration() -> None:
    """Re-running the _once registrar adds no overwrite history."""
    from hevi.riso.capabilities import register_riso_capabilities_once

    before = len(overwrite_history())
    first = register_riso_capabilities_once()
    second = register_riso_capabilities_once()
    assert len(overwrite_history()) == before
    assert [c.name for c in first] == [c.name for c in second]
    assert len({c.name for c in first}) == 10
    render_ids_before = {c.name: id(c.render) for c in first}
    register_riso_capabilities_once()
    render_ids_after = {c.name: id(c.render)
                        for c in list_capabilities()
                        if c.name.startswith("riso.")}
    assert render_ids_before == render_ids_after
    # Exactly one explicit overwrite=True capability call remains in-tree
    # (the intentional re-registration path inside register_riso_capabilities).
    source = (REPO_ROOT / "hevi/riso/capabilities.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    overwrite_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and any(kw.arg == "overwrite" and isinstance(kw.value, ast.Constant)
                and kw.value.value is True for kw in n.keywords)
    ]
    assert len(overwrite_calls) == 1


# -------------------------------------------------------------- compilers ---
COMPILER_MODULES = {
    "hevi/capabilities/prompt_compiler.py": "hevi.capabilities.prompt_compiler",
    "hevi/capabilities/structured_prompt_compiler.py":
        "hevi.capabilities.structured_prompt_compiler",
    "hevi/capabilities/director_handbook_compiler.py":
        "hevi.capabilities.director_handbook_compiler",
    "hevi/capabilities/edit_plan_compiler.py": "hevi.capabilities.edit_plan_compiler",
    "hevi/preflight/compiler.py": "hevi.preflight.compiler",
}


def test_compilers_no_shared_impl() -> None:
    """The five compilers share no implementation with each other.

    Shared code is allowed only via the grid helper and the duration
    tier table, which live outside all five modules.
    """
    imported: dict[str, set[str]] = {}
    for rel in COMPILER_MODULES:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
        imported[rel] = modules
    others = set(COMPILER_MODULES.values())
    for rel, modules in imported.items():
        assert not (modules & (others - {COMPILER_MODULES[rel]})), rel


# -------------------------------------------------------------- disclosure ---
def test_disclosure_tracks_independent() -> None:
    """Single-track pass must not imply dual-track pass; consent is separate."""
    from hevi.capabilities.ai_disclosure_gate import (
        check_ai_disclosure as check_single,
    )
    from hevi.capabilities.ai_disclosure_dual_track_gate import (
        check_ai_disclosure as check_dual,
    )
    from hevi.capabilities.portrait_consent import gate_portrait

    plan = {"frames": [{
        "depicts_real_person": False,
        "depicts_face": False,
        "person_status": "fictional",
        "ai_generated": True,
        "disclosure": "AI-generated",
    }]}
    assert check_single(plan)["verdict"] == "pass"
    assert check_dual(plan)["verdict"] == "fail"
    outcome = gate_portrait({
        "portrait_id": "p-unknown",
        "intended_use": "use",
        "registry": {"portraits": [
            {"portrait_id": "p-other", "consent": "authorized", "scope": ["use"]},
        ]},
    })
    assert outcome["allowed"] is False
    assert outcome["verdict"] == "refused_unknown_portrait"


# --------------------------------------------------------------- subtitles ---
def _parse_srt(text: str) -> list[dict[str, object]]:
    def to_sec(stamp: str) -> float:
        hms, ms = stamp.split(",")
        h, m, s = (float(p) for p in hms.split(":"))
        return h * 3600 + m * 60 + s + float(ms) / 1000

    events = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        start, end = lines[1].split(" --> ")
        events.append({
            "start_sec": to_sec(start),
            "end_sec": to_sec(end),
            "text": "\n".join(lines[2:]),
        })
    return events


def test_subtitle_pipeline_order() -> None:
    """narration_srt output passes the subtitle discipline gate."""
    from hevi.capabilities.narration_srt import build_srt
    from hevi.capabilities.subtitle_discipline import validate_events

    shots = [
        {"shot_id": "s1", "duration_sec": 2.0, "dialogue": "你好",
         "narration": ""},
        {"shot_id": "s2", "duration_sec": 2.0, "dialogue": "",
         "narration": "故事开始了"},
    ]
    srt = build_srt(shots)
    events = _parse_srt(srt)
    assert len(events) == 2
    report = validate_events(events, subtitle_bottom_fraction=0.2)
    assert report["verdict"] == "pass", report


# ------------------------------------------------- sibling docstring lists ---
DOCSTRING_EDGES = {
    "hevi/capabilities/alpha_cutout_keyer.py": ["check_chroma_key_evidence"],
    "hevi/capabilities/athenaion_session.py": ["create_graph"],
    "hevi/capabilities/athenaion_statue.py": ["build_column"],
    "hevi/capabilities/canvas_comfy_executor.py": ["check_model_install"],
    "hevi/capabilities/csk_styles.py": ["check_beats"],
    "hevi/capabilities/director_handbook_compiler.py": [
        "check_reference_numbering", "check_segment_match",
        "check_three_layer_clip", "render_three_layer_clip",
    ],
    "hevi/capabilities/event_trigger_wiring.py": ["validate_stage_block"],
    "hevi/capabilities/final_qc.py": ["measure_generation_consistency"],
    "hevi/capabilities/first_segment_confirmation_gate.py": ["check_review_signoff"],
    "hevi/capabilities/greenscreen_generation_gate.py": ["resolve_provider_caps"],
    "hevi/capabilities/minimal_stage_render.py": ["check_render_plan", "validate_stage_block"],
    "hevi/capabilities/page_contract.py": ["read_time_required_sec"],
    "hevi/capabilities/portrait_eight_dim_assembler.py": ["check_physical_language"],
    "hevi/capabilities/prompt_eval_harness.py": [
        "compile_generation_ready_episode", "build_three_layer_fixtures",
        "check_three_layer_clip",
    ],
    "hevi/capabilities/segment_assembly.py": ["record_critic_review"],
    "hevi/capabilities/subtitle_discipline.py": ["measure_generation_consistency"],
}

HELPER_IMPORTS = {
    "hevi/capabilities/asr_transcribe.py": ["_containment_coverage"],
    "hevi/capabilities/subtitle_discipline.py": ["_containment_coverage"],
    "hevi/capabilities/edit_plan_compiler.py": ["is_on_grid"],
    "hevi/capabilities/h3_frame_align_gate.py": ["is_on_grid", "snap_up"],
    "hevi/capabilities/issue_kind_labels.py": ["normalise_verdict"],
    "hevi/capabilities/h3_single_segment_adapter.py": [
        "is_on_grid", "check_frame_alignment", "check_stale_defaults",
    ],
}


def test_sibling_composition_lists_present() -> None:
    """Every restricted oskill->oskill edge lists its composition in a docstring."""
    for rel, names in DOCSTRING_EDGES.items():
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        docstrings = []
        module_doc = ast.get_docstring(tree)
        if module_doc:
            docstrings.append(module_doc)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                doc = ast.get_docstring(node)
                if doc:
                    docstrings.append(doc)
        blob = "\n".join(docstrings)
        for name in names:
            assert name in blob, f"{rel}: {name} missing from docstrings"


def test_pure_helper_imports_dissolve_element_edges() -> None:
    """Sunk helpers are imported from pure_helpers, not from element files."""
    for rel, names in HELPER_IMPORTS.items():
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        helper_imported = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom)
                    and node.module == "hevi.capabilities.pure_helpers"):
                helper_imported.update(a.name for a in node.names)
        for name in names:
            assert name in helper_imported, f"{rel}: {name} not from pure_helpers"
