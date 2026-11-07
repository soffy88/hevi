"""Material pack -> canvas mapping tests.

Covers: mapping completeness (prompt 1:1), idempotent remap, stale
revision protection, human-edit dirty + downstream review + history,
gate refusal, tail-frame pending semantics, reference-number
stability, adoption as a new version, and segment preflight cost.
Fixtures are invented for this file, mirroring the stable-film
manifest shape (17 segments, one pending-material segment). No
generation, network or real provider call is made.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from oprim.hevi_types import CanvasNode

from hevi.canvas.material_pack import (
    MaterialPackError,
    adopt_segment_edit,
    apply_segment_edit,
    check_regeneration_gates,
    map_to_graph,
    normalize_material_pack,
    request_regeneration,
)
from hevi.canvas.preflight import estimate_graph_cost


def _shot(shot_id: str, text: str, duration: float) -> dict[str, Any]:
    return {"shot_id": shot_id, "scene_id": "main", "text": text, "duration_sec": duration}


def _manifest_like() -> dict[str, Any]:
    """17 segments in the stable-film manifest shape; seg-06 pending."""
    segments: list[dict[str, Any]] = []
    all_shots: list[str] = []
    for i in range(1, 18):
        seg_id = f"seg-{i:02d}"
        if i == 6:
            shots = [
                _shot("s06-1", "invented line one", 5.0),
                _shot("s06-2", "invented line two", 5.0),
                _shot("s06-3", "invented line three", 4.59),
            ]
        else:
            shots = [
                _shot(f"s{i:02d}-1", f"invented line {i} one", 5.0),
                _shot(f"s{i:02d}-2", f"invented line {i} two", 4.0),
            ]
        all_shots.extend(s["shot_id"] for s in shots)
        segments.append(
            {
                "segment_id": seg_id,
                "generation_node": seg_id,
                "scene_ids": ["main"],
                "shot_ids": [s["shot_id"] for s in shots],
                "shots": shots,
                "duration_sec": round(sum(s["duration_sec"] for s in shots), 3),
            }
        )
    pending = ["s06-1", "s06-2", "s06-3"]
    return {
        "capability": "pipeline.stable_film_assembly",
        "title": "Invented stars film",
        "status": "partial",
        "delivery_note": "partial | pending: s06-1, s06-2, s06-3",
        "duration_sec": 197.7,
        "gates": [
            {"gate": "video.segment_assembly_gate", "verdict": "pass",
             "detail": "17 segments"},
            {"gate": "story.asset_registry_v2", "verdict": "pending",
             "detail": "pending material for shots: s06-1, s06-2, s06-3"},
            {"gate": "edit.subtitle_discipline", "verdict": "fail",
             "detail": "stale_timeline"},
        ],
        "failed_gates": ["edit.subtitle_discipline"],
        "pending_material": [
            {"shot_id": s, "asset_id": "sky",
             "reason": "scene image not generated in free route"} for s in pending
        ],
        "pending_shot_ids": pending,
        "generation_shot_ids": [s for s in all_shots if s not in pending],
        "segment_plan": {"segments": segments},
    }


def _full_pack(n: int = 15) -> dict[str, Any]:
    """Explicit pack with compiled prompts on every segment."""
    segments: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        seg_id = f"seg-{i:02d}"
        shots = [
            _shot(f"s{i:02d}-1", f"compiled narration {i} one", 4.0),
            _shot(f"s{i:02d}-2", f"compiled narration {i} two", 5.0),
        ]
        segments.append(
            {
                "segment_id": seg_id,
                "duration_sec": 9.0,
                "asset_ids": ["char-a", "scene-b"],
                "shots": shots,
                "compiled_prompt": {
                    "prompt": f"[compiled prompt {i}] scene with easing",
                    "negative_prompts": ["no text", "no watermark"],
                    "easing": "linear",
                    "fallbacks": [
                        {"trigger": "model refuses", "replacement": "simpler framing"}
                    ],
                    "reference_numbers": [1, 2],
                    "reference_order": ["char-a", "scene-b"],
                    "first_frame_ref": f"frames/{seg_id}-first.jpg",
                    "tail_frame_ref": f"frames/{seg_id}-tail.jpg",
                    "asset_version": "v1",
                },
            }
        )
    return {
        "pack_id": "pack-invented",
        "title": "Invented full pack",
        "status": "done",
        "segments": segments,
        "generation_shot_ids": [s["shot_id"] for seg in segments for s in seg["shots"]],
        "assets": [
            {"asset_id": "char-a", "kind": "character", "version": "v1", "status": "done"},
            {"asset_id": "scene-b", "kind": "scene", "version": "v1", "status": "done"},
        ],
    }


def _configs(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["node_id"]: n.get("config") or {} for n in graph["nodes"]}


# ── 1. Normalisation: manifest is the fact source ────────────────────────


def test_manifest_normalisation_marks_missing_compiled_fields() -> None:
    pack = normalize_material_pack(_manifest_like())
    assert pack["source"] == "stable_film_manifest"
    assert len(pack["segments"]) == 17
    # The manifest's own status wins verbatim ("partial"); the
    # pending-material fact lives on seg-06 and the pack gates.
    assert pack["status"] == "partial"
    seg06 = pack["segments"][5]
    assert seg06["segment_id"] == "seg-06"
    assert seg06["status"] == "pending-material"
    assert seg06["gate_badges"] and seg06["gate_badges"][0]["gate"] == "story.asset_registry_v2"
    seg01 = pack["segments"][0]
    # Prompt is the shots' narration verbatim; compiled fields missing, not guessed.
    assert seg01["prompt"] == "invented line 1 one\ninvented line 1 two"
    assert seg01["prompt_source"] == "manifest_narration"
    for field in ("negative_prompts", "easing", "fallbacks", "reference_numbers",
                  "reference_order", "first_frame_ref", "tail_frame_ref",
                  "asset_version"):
        assert field in seg01["missing_fields"]
    # Film-level subtitle failure is NOT smeared onto segments.
    assert all(
        b["gate"] != "edit.subtitle_discipline"
        for s in pack["segments"] for b in s["gate_badges"]
    )
    assert any(g["gate"] == "edit.subtitle_discipline" for g in pack["gates"])
    asset_ids = {a["asset_id"] for a in pack["assets"]}
    assert "sky" in asset_ids and "main" in asset_ids
    sky = next(a for a in pack["assets"] if a["asset_id"] == "sky")
    assert sky["status"] == "pending-material"


def test_duplicate_asset_versions_are_refused() -> None:
    pack = _full_pack(2)
    pack["assets"].append(
        {"asset_id": "char-a", "kind": "character", "version": "v2", "status": "done"}
    )
    with pytest.raises(MaterialPackError, match="two versions"):
        normalize_material_pack(pack)


def test_duplicate_segment_ids_are_refused() -> None:
    pack = _full_pack(2)
    pack["segments"].append(copy.deepcopy(pack["segments"][0]))
    with pytest.raises(MaterialPackError, match="duplicate segment_id"):
        normalize_material_pack(pack)


# ── 2. Mapping completeness + prompt correspondence ─────────────────────


def test_full_pack_maps_every_segment_with_prompt_one_to_one() -> None:
    pack = normalize_material_pack(_full_pack(15))
    mapped = map_to_graph(pack)
    graph = mapped["graph"]
    segment_nodes = [n for n in graph["nodes"] if n["node_type"] == "segment"]
    asset_nodes = [n for n in graph["nodes"] if n["node_type"] == "asset"]
    assert len(segment_nodes) == 15
    assert len(asset_nodes) == 2
    configs = _configs(graph)
    for segment in pack["segments"]:
        cfg = configs[segment["segment_id"]]
        assert cfg["prompt"] == segment["prompt"]
        assert cfg["negative_prompts"] == ["no text", "no watermark"]
        assert cfg["easing"] == "linear"
        assert cfg["reference_numbers"] == [1, 2]
        assert cfg["duration_s"] == 9.0
        assert cfg["material_pack_status"] == "done"
    continuations = [e for e in graph["edges"] if e.get("kind") == "continuation"]
    references = [e for e in graph["edges"] if e.get("kind") == "reference"]
    assert len(continuations) == 14
    assert all(e["status"] == "connected" for e in continuations)
    assert all(e["from_type"] == "segment" and e["to_type"] == "segment"
               for e in continuations)
    assert len(references) == 30
    assert all(e["from_type"] == "asset" and e["to_type"] == "segment"
               for e in references)
    assert mapped["report"]["segment_count"] == 15
    assert mapped["report"]["continuation_connected"] == 14
    assert mapped["report"]["continuation_pending"] == 0


def test_manifest_mapping_marks_missing_tail_frames_pending() -> None:
    mapped = map_to_graph(_manifest_like())
    graph = mapped["graph"]
    assert len([n for n in graph["nodes"] if n["node_type"] == "segment"]) == 17
    continuations = [e for e in graph["edges"] if e.get("kind") == "continuation"]
    assert len(continuations) == 16
    assert all(e["status"] == "pending" for e in continuations)
    assert mapped["report"]["continuation_pending"] == 16
    sky_edges = [e for e in graph["edges"]
                 if e.get("from_node_id") == "asset-sky"]
    assert [e["to_node_id"] for e in sky_edges] == ["seg-06"]
    assert mapped["report"]["gate_summary"][0]["gate"] == "video.segment_assembly_gate"


def test_map_to_graph_accepts_raw_manifest_dict() -> None:
    mapped = map_to_graph(_manifest_like())
    assert mapped["report"]["source"] == "stable_film_manifest"


# ── 3. Idempotency + revision protection ────────────────────────────────


def test_remap_is_idempotent() -> None:
    pack = normalize_material_pack(_full_pack(12))
    first = map_to_graph(pack)["graph"]
    second_mapped = map_to_graph(pack, first)
    second = second_mapped["graph"]
    assert len(second["nodes"]) == len(first["nodes"])
    assert len(second["edges"]) == len(first["edges"])
    assert [n["node_id"] for n in second["nodes"]] == [n["node_id"] for n in first["nodes"]]
    assert second_mapped["report"]["added_nodes"] == []
    assert _configs(second) == _configs(first)


def test_stale_revision_never_overwrites_newer_node() -> None:
    pack = normalize_material_pack(_full_pack(3))
    newer = map_to_graph(pack, pack_revision=2)["graph"]
    remapped = map_to_graph(pack, newer, pack_revision=1)
    assert remapped["report"]["stale_skipped"] == [
        "seg-01", "seg-02", "seg-03", "asset-char-a", "asset-scene-b",
    ]
    assert _configs(remapped["graph"]) == _configs(newer)


def test_newer_revision_adopts_and_keeps_old_prompt_in_history() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack, pack_revision=1)["graph"]
    pack2 = normalize_material_pack(_full_pack(3))
    pack2["segments"][0]["prompt"] = "[compiled prompt 1] revised scene"
    remapped = map_to_graph(pack2, graph, pack_revision=2)
    cfg = _configs(remapped["graph"])["seg-01"]
    assert cfg["prompt"] == "[compiled prompt 1] revised scene"
    assert cfg["material_pack_prompt_history"][0]["prompt"] == \
        "[compiled prompt 1] scene with easing"
    assert remapped["report"]["updated_nodes"] == [
        "seg-01", "seg-02", "seg-03", "asset-char-a", "asset-scene-b",
    ]


# ── 4. Human edit loop ──────────────────────────────────────────────────


def test_edit_marks_dirty_and_downstream_review_only() -> None:
    pack = normalize_material_pack(_full_pack(5))
    graph = map_to_graph(pack)["graph"]
    before = _configs(graph)
    edited = apply_segment_edit(
        graph, "seg-02",
        {"prompt": "[edited prompt 2]", "duration_sec": 8.0},
        base_revision=1,
    )["graph"]
    configs = _configs(edited)
    seg02 = configs["seg-02"]
    assert seg02["prompt"] == "[edited prompt 2]"
    assert seg02["duration_s"] == 8.0
    assert seg02["material_pack_dirty"] is True
    assert seg02["material_pack_review_pending"] is True
    assert len(seg02["material_pack_prompt_history"]) == 1
    assert seg02["material_pack_prompt_history"][0]["prompt"] == \
        "[compiled prompt 2] scene with easing"
    # Upstream untouched; downstream flagged but prompts/results untouched.
    assert configs["seg-01"]["material_pack_review_pending"] is False
    for seg_id in ("seg-03", "seg-04", "seg-05"):
        assert configs[seg_id]["material_pack_review_pending"] is True
        assert configs[seg_id]["prompt"] == before[seg_id]["prompt"]
        assert configs[seg_id]["material_pack_prompt_history"] == []


def test_edit_preserves_dirty_prompt_on_same_revision_remap() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    edited = apply_segment_edit(
        graph, "seg-02", {"prompt": "[edited prompt 2]"}, base_revision=1
    )["graph"]
    remapped = map_to_graph(pack, edited)
    assert remapped["report"]["preserved_dirty"] == ["seg-02"]
    assert _configs(remapped["graph"])["seg-02"]["prompt"] == "[edited prompt 2]"


def test_edit_rejects_unknown_fields_empty_prompt_and_stale_revision() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    with pytest.raises(MaterialPackError, match="cannot edit"):
        apply_segment_edit(graph, "seg-01", {"title": "x"}, base_revision=1)
    with pytest.raises(MaterialPackError, match="non-empty"):
        apply_segment_edit(graph, "seg-01", {"prompt": "  "}, base_revision=1)
    with pytest.raises(MaterialPackError, match="stale"):
        apply_segment_edit(graph, "seg-01", {"prompt": "x"}, base_revision=99)
    with pytest.raises(MaterialPackError, match="no segment node"):
        apply_segment_edit(graph, "seg-99", {"prompt": "x"}, base_revision=1)


def test_reference_numbers_are_never_renumbered() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    # Model capability gap: order has 2 entries, edit stores number 3.
    edited = apply_segment_edit(
        graph, "seg-01", {"reference_numbers": [1, 3]}, base_revision=1
    )["graph"]
    cfg = _configs(edited)["seg-01"]
    assert cfg["reference_numbers"] == [1, 3]
    assert any("no entry in the declared reference order" in n
               for n in cfg["material_pack_review_notes"])
    # A remap does not renumber either.
    remapped = map_to_graph(pack, edited)
    assert _configs(remapped["graph"])["seg-01"]["reference_numbers"] == [1, 3]


def test_edit_can_change_negative_list_duration_and_first_frame() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    edited = apply_segment_edit(
        graph, "seg-01",
        {"negative_prompts": ["no blur"], "duration_sec": 7.5,
         "first_frame_ref": "frames/seg-01-first-v2.jpg"},
        base_revision=1,
    )["graph"]
    cfg = _configs(edited)["seg-01"]
    assert cfg["negative_prompts"] == ["no blur"]
    assert cfg["duration_sec"] == 7.5
    assert cfg["first_frame_ref"] == "frames/seg-01-first-v2.jpg"


# ── 5. Gates + regeneration ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_failure_refuses_regeneration() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    # Over-cap duration breaks the segment-assembly gate.
    edited = apply_segment_edit(
        graph, "seg-01", {"duration_sec": 20.0}, base_revision=1
    )["graph"]
    gates = check_regeneration_gates(edited, "seg-01")
    assert gates["ok"] is False
    result = await request_regeneration(edited, "seg-01", free_route=True)
    assert result["status"] == "refused"
    assert any("segment_assembly" in b for b in result["blockers"])


@pytest.mark.asyncio
async def test_pending_material_refuses_regeneration() -> None:
    pack = normalize_material_pack(_manifest_like())
    graph = map_to_graph(pack)["graph"]
    result = await request_regeneration(graph, "seg-06", free_route=True)
    assert result["status"] == "refused"
    assert any("pending material" in b for b in result["blockers"])


@pytest.mark.asyncio
async def test_free_route_ready_and_paid_needs_strict_confirmation() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    ready = await request_regeneration(graph, "seg-01", free_route=True)
    assert ready["status"] == "ready"
    assert ready["scope"] == "single_segment"
    assert ready["spend"]["mode"] == "free_route"
    assert all(g["verdict"] == "pass" for g in ready["gates"])
    refused = await request_regeneration(graph, "seg-01", free_route=False)
    assert refused["status"] == "refused"
    assert any("confirmed" in b for b in refused["blockers"])
    paid = await request_regeneration(
        graph, "seg-01", free_route=False, confirmed=True
    )
    assert paid["status"] == "ready"
    assert paid["spend"]["approved"] is True


@pytest.mark.asyncio
async def test_executor_receives_only_the_one_segment() -> None:
    pack = normalize_material_pack(_full_pack(4))
    graph = map_to_graph(pack)["graph"]
    seen: list[str] = []

    async def fake_executor(node: dict[str, Any]) -> dict[str, Any]:
        seen.append(node["node_id"])
        return {"ok": True}

    result = await request_regeneration(
        graph, "seg-02", free_route=True, executor=fake_executor
    )
    assert result["status"] == "executed"
    assert seen == ["seg-02"]


@pytest.mark.asyncio
async def test_preflight_budget_refuses_over_budget_segment() -> None:
    pack = normalize_material_pack(_full_pack(2))
    pack["segments"][0]["provider"] = "veo3"
    graph = map_to_graph(pack)["graph"]
    result = await request_regeneration(
        graph, "seg-01", free_route=False, confirmed=True, budget_usd=0.01
    )
    assert result["status"] == "refused"
    assert any("预算" in b or "budget" in b.lower() or "超出" in b
               for b in result["blockers"])


def test_segment_nodes_count_in_preflight_cost() -> None:
    nodes = [
        CanvasNode(node_id="s1", node_type="segment",
                   config={"provider": "veo3", "duration_s": 8.0}),
        CanvasNode(node_id="t1", node_type="text", config={"content": "x"}),
    ]
    assert abs(estimate_graph_cost(nodes) - 0.40) < 1e-6


# ── 6. Adoption ─────────────────────────────────────────────────────────


def test_adopt_writes_new_version_and_keeps_old() -> None:
    pack = normalize_material_pack(_full_pack(4))
    graph = map_to_graph(pack)["graph"]
    edited = apply_segment_edit(
        graph, "seg-02", {"prompt": "[adopted prompt 2]"}, base_revision=1
    )["graph"]
    adopted = adopt_segment_edit(pack, edited, "seg-02")
    new_pack = adopted["pack"]
    assert adopted["report"] == {
        "segment_id": "seg-02",
        "old_revision": 1,
        "new_revision": 2,
        "versions_retained": 1,
        "downstream_still_pending": ["seg-03", "seg-04"],
    }
    new_segment = new_pack["segments"][1]
    assert new_segment["revision"] == 2
    assert new_segment["prompt"] == "[adopted prompt 2]"
    assert len(new_segment["versions"]) == 1
    assert new_segment["versions"][0]["prompt"] == "[compiled prompt 2] scene with easing"
    cfg = _configs(adopted["graph"])["seg-02"]
    assert cfg["material_pack_revision"] == 2
    assert cfg["material_pack_dirty"] is False
    # Downstream stays pending review after adoption.
    assert _configs(adopted["graph"])["seg-03"]["material_pack_review_pending"] is True
    # The input pack is untouched: unadopted edits never write back.
    assert pack["segments"][1]["prompt"] == "[compiled prompt 2] scene with easing"


def test_adopt_without_edit_or_with_failing_gates_is_refused() -> None:
    pack = normalize_material_pack(_full_pack(3))
    graph = map_to_graph(pack)["graph"]
    with pytest.raises(MaterialPackError, match="no unadopted edit"):
        adopt_segment_edit(pack, graph, "seg-01")
    edited = apply_segment_edit(
        graph, "seg-01", {"duration_sec": 20.0}, base_revision=1
    )["graph"]
    with pytest.raises(MaterialPackError, match="gates did not pass"):
        adopt_segment_edit(pack, edited, "seg-01")


# ── 7. Router surface ───────────────────────────────────────────────────


def test_canvas_router_exposes_material_pack_routes() -> None:
    from hevi.api.routers.canvas import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/canvas/material-pack/graph" in paths
    assert "/canvas/material-pack/edit" in paths
    assert "/canvas/material-pack/regenerate" in paths
