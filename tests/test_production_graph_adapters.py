from __future__ import annotations

from hevi.production_graph.adapters import chapter_to_narrative, novel_plan_to_narrative
from hevi.production_graph.ids import stable_id
from hevi.script2video.adapter_schemas import NovelEvent, NovelPlan
from hevi.tongjian.schemas import ChapterIR, ChapterMeta, CharacterIR, EventIR


def test_tongjian_adapter_preserves_source_span_and_causal_edges() -> None:
    chapter = ChapterIR(
        meta=ChapterMeta(source="public domain"),
        characters=[CharacterIR(character_id="C001", canonical_name="A")],
        events=[
            EventIR(event_id="E001", summary="arrival", source_span=(2, 8)),
            EventIR(
                event_id="E002",
                summary="conflict",
                actors=["C001"],
                causes=["E001"],
                source_span=(9, 15),
            ),
        ],
    )
    graph = chapter_to_narrative(
        chapter,
        project_id="project",
        revision_id="revision",
        source_document_id="document",
    )

    assert graph.events[1].source_refs[0].start_offset == 9
    assert graph.events[1].character_ids == [stable_id("character", "project:tongjian:C001")]
    assert graph.events[1].causes == [stable_id("narrative-event", "project:tongjian:E001")]
    assert graph.edges[0].type.value == "CAUSES"
    assert graph.edges[0].source_refs[0].document_id == "document"


def test_novel_adapter_preserves_cross_event_order_and_source_binding() -> None:
    plan = NovelPlan(
        original_chars=10,
        compressed="compressed",
        compression_ratio=0.5,
        events=[
            NovelEvent(index=0, description="one", process_chain=[]),
            NovelEvent(index=1, description="two", process_chain=[], is_last=True),
        ],
        scenes=[],
        book=[],
    )
    graph = novel_plan_to_narrative(
        plan, project_id="p", revision_id="r", source_document_id="source"
    )

    assert [event.temporal_order for event in graph.events] == [0, 1]
    assert graph.events[0].source_refs[0].document_id == "source"
    assert graph.edges[0].type.value == "PRECEDES"
