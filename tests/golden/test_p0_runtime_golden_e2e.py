"""Real product-orchestration Golden A/B/C acceptance paths."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from hevi.production_graph.orchestration import (
    historical_product_entrypoint,
    long_form_product_entrypoint,
    one_prompt_product_entrypoint,
)
from hevi.production_graph.repository import ProductionGraphRepository
from hevi.tongjian.schemas import ChapterIR, ChapterMeta, CharacterIR, EventIR

ROOT = Path(__file__).parents[2]


def _chapter(source: str, event_rows: list[dict[str, object]]) -> ChapterIR:
    events = []
    for row in event_rows:
        span = row.get("span", (0, len(str(row["summary"]))))
        events.append(
            EventIR(
                event_id=str(row["id"]),
                summary=str(row["summary"]),
                actors=["hero"],
                causes=list(row.get("causes", [])),
                effects=list(row.get("effects", [])),
                source_span=tuple(span),
            )
        )
    return ChapterIR(
        meta=ChapterMeta(source=source),
        characters=[
            CharacterIR(character_id="hero", canonical_name="Envoy", role_in_chapter="protagonist")
        ],
        events=events,
    )


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
    assert _media_qa(tmp_path / "gold-a.mp4", 3.0)


@pytest.mark.golden
def test_gold_b_long_form_product_runtime_e2e(tmp_path: Path) -> None:
    chapters = [
        _chapter(
            "public-domain chapter one",
            [
                {
                    "id": "arrival",
                    "summary": "The envoy arrives with a sealed dispatch.",
                    "span": (0, 42),
                },
                {
                    "id": "warning",
                    "summary": "The warden warns that the road is watched.",
                    "causes": ["arrival"],
                    "span": (43, 86),
                },
            ],
        ),
        _chapter(
            "public-domain chapter two",
            [
                {
                    "id": "pursuit",
                    "summary": "The pursuit begins after the gate closes.",
                    "span": (0, 43),
                },
                {
                    "id": "delivery",
                    "summary": "The envoy delivers the dispatch beyond the gate.",
                    "causes": ["pursuit"],
                    "span": (44, 92),
                },
            ],
        ),
    ]
    run = asyncio.run(
        long_form_product_entrypoint(
            ProductionGraphRepository(),
            chapters=chapters,
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
    assert _media_qa(tmp_path / "gold-b.mp4", 3.0)


@pytest.mark.golden
def test_gold_c_one_prompt_real_product_path(tmp_path: Path) -> None:
    raw = "Make a tense 12-second vertical scene of an envoy crossing an old gate at dawn."
    run = asyncio.run(
        one_prompt_product_entrypoint(
            ProductionGraphRepository(),
            raw_request=raw,
            user_id="gold-c",
            render_path=tmp_path / "gold-c.mp4",
        )
    )
    snapshot = run.snapshot
    assert snapshot.project.creative_brief == raw
    assert snapshot.director_sessions and snapshot.director_decisions
    assert snapshot.production_plans and snapshot.shots
    assert run.entrypoint == "POST /studio/one-prompt"
    assert run.manifest and run.manifest.artifacts[0].integrity_ok()
    assert _media_qa(tmp_path / "gold-c.mp4", 12.0)


@pytest.mark.golden
def test_gold_acceptance_guards_require_execution_provenance() -> None:
    from hevi.production_graph.provenance import validate_creative_provenance

    run = asyncio.run(
        historical_product_entrypoint(
            ProductionGraphRepository(),
            source_text="A source event.",
            title="Guard",
            user_id="guard",
        )
    )
    report = validate_creative_provenance(run.snapshot)
    assert report.broken_edges == 0
    assert report.unbound_final_artifacts == 1
