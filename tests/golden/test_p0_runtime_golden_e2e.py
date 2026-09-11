"""Real product-orchestration Golden A/B/C acceptance paths."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from hevi.api.main import app
from hevi.api.routers import studio_v2
from hevi.auth.dependencies import get_current_user
from hevi.production_graph.orchestration import (
    historical_product_entrypoint,
    long_form_product_entrypoint,
)
from hevi.production_graph.provenance import validate_creative_provenance
from hevi.production_graph.repository import ProductionGraphRepository

ROOT = Path(__file__).parents[2]


def _media_qa(path: Path, duration: float) -> str:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=nw=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "codec_type=video" in probe.stdout
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], check=True)
    duration_probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(duration_probe.stdout.strip()) >= duration - 0.5
    assert path.stat().st_size > 1024
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.golden
def test_gold_a_historical_product_runtime_e2e(tmp_path: Path) -> None:
    source = json.loads((ROOT / "tests/golden/gold_a_historical.json").read_text())
    run = asyncio.run(
        historical_product_entrypoint(
            ProductionGraphRepository(),
            source_text=source["source_text"],
            title=source["title"],
            user_id="gold-a",
            render_path=tmp_path / "gold-a.mp4",
        )
    )
    snapshot = run.snapshot
    assert len(snapshot.narrative.events) >= 2
    assert len(snapshot.scenes) >= 1 and len(snapshot.shots) >= 1
    assert snapshot.sources[0].id and snapshot.source_chunks[0].id
    assert any(
        link.source_type == "SourceChunk" and link.target_type == "NarrativeEvent"
        for link in snapshot.provenance_links
    )
    assert run.manifest and run.manifest.artifacts[0].integrity_ok()
    report = validate_creative_provenance(snapshot)
    assert report.broken_edges == 0
    assert report.orphan_nodes == 0
    assert report.unbound_final_artifacts == 0
    assert _media_qa(tmp_path / "gold-a.mp4", 3.0)


@pytest.mark.golden
def test_gold_b_long_form_product_runtime_e2e(tmp_path: Path) -> None:
    source = (ROOT / "tests/golden/gold_b_long_form.txt").read_text()
    run = asyncio.run(
        long_form_product_entrypoint(
            ProductionGraphRepository(),
            source_text=source,
            title="Gold B — The sealed route",
            user_id="gold-b",
            render_path=tmp_path / "gold-b.mp4",
        )
    )
    snapshot = run.snapshot
    assert len(snapshot.episodes) >= 2
    assert len(snapshot.narrative.events) >= 4
    assert len(snapshot.scenes) >= 4 and len(snapshot.shots) >= 4
    assert snapshot.narrative.plot_threads
    assert any(edge.type.value == "CAUSES" for edge in snapshot.narrative.edges)
    assert len({state.look_variant_id for state in snapshot.character_states}) >= 2
    assert len({state.weather for state in snapshot.location_states}) >= 2
    assert len({state.condition for state in snapshot.prop_states}) >= 2
    assert run.manifest and run.manifest.artifacts[0].integrity_ok()
    report = validate_creative_provenance(snapshot)
    assert report.broken_edges == 0
    assert report.orphan_nodes == 0
    assert report.unbound_final_artifacts == 0
    assert _media_qa(tmp_path / "gold-b.mp4", 3.0)


@pytest.mark.golden
def test_gold_c_one_prompt_real_product_path(tmp_path: Path) -> None:
    raw = "Make a tense 12-second vertical scene of an envoy crossing an old gate at dawn."
    repo = ProductionGraphRepository()
    user = {"id": "gold-c", "is_active": True}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[studio_v2.get_graph_repository] = lambda: repo
    try:
        response = asyncio.run(
            studio_v2.one_prompt(
                studio_v2.OnePromptRequest(request=raw, render_path=str(tmp_path / "gold-c.mp4")),
                user,
                repo,
            )
        )
    finally:
        app.dependency_overrides.clear()
    snapshot = asyncio.run(repo.get_snapshot(response["project_id"]))
    assert snapshot is not None
    assert snapshot.project.creative_brief == raw
    assert snapshot.director_sessions and snapshot.director_decisions
    assert snapshot.production_plans and snapshot.shots
    assert response["execution_attempt_id"]
    assert response["artifact_id"]
    assert _media_qa(tmp_path / "gold-c.mp4", 12.0)


@pytest.mark.golden
def test_gold_acceptance_guards_require_execution_provenance() -> None:
    from hevi.production_graph.provenance import validate_creative_provenance

    run = asyncio.run(
        historical_product_entrypoint(
            ProductionGraphRepository(),
            source_text="A source event. A second source event.",
            title="Guard",
            user_id="guard",
        )
    )
    report = validate_creative_provenance(run.snapshot)
    assert report.broken_edges == 0
    assert report.unbound_final_artifacts == 1


@pytest.mark.golden
def test_gold_acceptance_guards_reject_missing_execution_plan() -> None:
    run = asyncio.run(
        historical_product_entrypoint(
            ProductionGraphRepository(),
            source_text="Arrival. Delivery.",
            title="Guard",
            user_id="guard",
        )
    )
    broken = run.snapshot.model_copy(update={"execution_plans": []})
    report = validate_creative_provenance(broken)
    assert report.broken_edges >= 1
