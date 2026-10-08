"""P0.8 — the OpenReel seam, tested with OpenReel absent.

§54: "OpenReel unavailable 不得阻塞 HEVI core tests." OpenReel is genuinely absent from
this repository -- no package, no sibling checkout, no dependency -- so this file tests
the seam in exactly the state it will run in.

Two things are being asserted, and the distinction matters:

* the **mapping** is real and complete for the operation types it covers
* the **execution** path is blocked, loudly, and is reported as BLOCKED rather than
  quietly skipped

A test suite that passed because the adapter was never exercised would be worse than
no suite. So the fake-runner tests drive the full execute() path, and the unavailability
test asserts a *raised* exception rather than a graceful no-op.
"""

from __future__ import annotations

import pytest

from hevi.adapters.openreel import (
    OpenReelArtifact,
    OpenReelUnavailable,
)
from hevi.adapters.openreel.execution_adapter import OpenReelExecutionAdapter
from hevi.adapters.openreel.operation_mapper import (
    UnsupportedOperation,
    expected_outputs_for,
    map_operation,
)
from hevi.adapters.openreel.receipt_mapper import (
    RenderMappingError,
    mark_succeeded,
    to_artifact_ref,
    to_render_job,
    to_render_receipt,
)
from hevi.adapters.openreel.render_mapper import render_request
from hevi.production.execution_executor import ExecutionContext
from hevi.production.operation import (
    ArtifactExpectation,
    ProductionOperation,
    ProductionOperationType,
)
from hevi.production.timeline_ir import Canvas, TimelineClip, TimelineIR, TrackKind


def _op(
    operation_type: ProductionOperationType, **params
) -> ProductionOperation:
    return ProductionOperation(
        operation_id=f"op-{operation_type.value.lower()}",
        operation_type=operation_type,
        production_id="prod-1",
        parameters=params,
        idempotency_key="k",
    )


# ── §42 one-to-many mapping ──


def test_visual_scene_fans_out_into_several_actions():
    """§42: one HEVI operation, several OpenReel actions."""
    actions = map_operation(
        _op(ProductionOperationType.VISUAL_SCENE, duration_ms=2000, text="Hi",
            transform={"x": 0}, keyframes=[{"t": 0}])
    )
    assert [a.action_type for a in actions] == [
        "create_track", "create_clip", "set_transform", "set_text", "set_keyframe",
    ]


def test_mapped_actions_carry_their_dependencies():
    """OpenReel's runner needs ordering; HEVI does not trust it back."""
    actions = {a.action_type: a for a in map_operation(
        _op(ProductionOperationType.VISUAL_SCENE, duration_ms=100, text="x")
    )}
    assert actions["create_track"].depends_on == ()
    assert actions["create_clip"].depends_on == ("create_track",)
    assert actions["set_text"].depends_on == ("create_clip",)


def test_mapping_is_deterministic():
    """The same operation must produce the same actions, in the same order.

    A mapping that varied would produce different timelines per run and defeat both
    idempotency and the render cache.
    """
    op = _op(ProductionOperationType.VISUAL_SCENE, duration_ms=2000, text="Hi")
    assert map_operation(op) == map_operation(op)


def test_unmapped_operation_raises_rather_than_returning_empty():
    """An empty tuple would read to a caller as 'ran and produced nothing' (§35)."""
    with pytest.raises(UnsupportedOperation, match="OPENREEL_UNMAPPED_OPERATION"):
        map_operation(_op(ProductionOperationType.SUBTITLE))


# ── §3.3 MEDIA must not select assets ──


def test_media_without_a_resolved_source_is_refused():
    """The adapter cannot choose an asset; that is the canonical selector's job.

    §62 lists a renderer or adapter choosing assets as prohibited. Silently picking
    something would make the adapter an asset selector.
    """
    with pytest.raises(UnsupportedOperation, match="WITHOUT_RESOLVED_SOURCE"):
        map_operation(_op(ProductionOperationType.MEDIA))


def test_media_with_a_resolved_source_maps_cleanly():
    actions = map_operation(
        _op(ProductionOperationType.MEDIA, resolved_source="/tmp/a.mp4", kind="video")
    )
    assert [a.action_type for a in actions] == ["import_media"]
    assert actions[0].payload["source"] == "/tmp/a.mp4"


# ── §3.1 timeline semantics are not forwarded ──


def test_timeline_mapping_forwards_only_timeline_fields():
    """A timeline action must not carry semantic intent.

    Forwarding it would let an OpenReel timeline become a second semantic authority
    (§3.1, §62).
    """
    actions = map_operation(
        _op(ProductionOperationType.TIMELINE, timeline_id="tl", track="video",
            duration_ms=1000, semantic_intent="make it feel hopeful")
    )
    payload = actions[0].payload
    assert "semantic_intent" not in payload
    assert payload["timeline_id"] == "tl"


# ── §43 output expectations pass through unchanged ──


def test_expected_outputs_are_not_invented_or_dropped():
    op = ProductionOperation(
        operation_id="op", operation_type=ProductionOperationType.RENDER,
        production_id="p", idempotency_key="k",
        expected_outputs=(ArtifactExpectation(name="final", kind="video", required=True),),
    )
    assert expected_outputs_for(op) == op.expected_outputs


# ── §54 unavailability ──


def test_adapter_reports_itself_unavailable_without_a_runner():
    assert OpenReelExecutionAdapter().can_execute(
        _op(ProductionOperationType.VISUAL_SCENE)
    ) is False


def test_execution_without_a_runner_raises_loudly():
    """Not a graceful no-op. §35 forbids a failure that reads as success."""
    adapter = OpenReelExecutionAdapter()
    with pytest.raises(OpenReelUnavailable, match="OPENREEL_RUNTIME_UNAVAILABLE"):
        adapter.execute(
            _op(ProductionOperationType.VISUAL_SCENE),
            ExecutionContext(production_id="p", transaction_id="t"),
        )


def test_a_failing_runner_surfaces_as_a_typed_adapter_error():
    from hevi.production.execution_result import AdapterError

    class BrokenRunner:
        def available(self) -> bool:
            return True

        def run_actions(self, actions, work_dir=None):
            raise RuntimeError("openreel exploded")

    with pytest.raises(AdapterError) as excinfo:
        OpenReelExecutionAdapter(BrokenRunner()).execute(
            _op(ProductionOperationType.VISUAL_SCENE),
            ExecutionContext(production_id="p", transaction_id="t"),
        )
    # The declared kind is what the retry policy reads, so it is asserted explicitly
    # rather than left implicit in the exception type.
    assert excinfo.value.error_type == "provider_unavailable"


def test_injected_runner_drives_the_full_execute_path():
    """Proves the seam works, without needing OpenReel installed."""
    class FakeRunner:
        def available(self) -> bool:
            return True

        def run_actions(self, actions, work_dir=None):
            assert actions, "the adapter must forward actions to the runner"
            return (OpenReelArtifact(artifact_id="art-1", uri="/tmp/art-1.bin",
                                     content_hash="ab" * 32, kind="video"),)

    adapter = OpenReelExecutionAdapter(FakeRunner())
    op = _op(ProductionOperationType.VISUAL_SCENE)
    assert adapter.can_execute(op) is True
    result = adapter.execute(op, ExecutionContext(production_id="p", transaction_id="t"))
    assert result.succeeded
    assert result.artifacts == ("art-1",)
    assert result.metadata["hash:art-1"] == "ab" * 32


# ── §13 TimelineIR projection is one-way ──


def _timeline() -> TimelineIR:
    return TimelineIR(
        project_id="proj-1",
        canvas=Canvas(width=1080, height=1920, fps=30),
        clips=(
            TimelineClip(clip_id="c1", track=TrackKind.VIDEO, source_path="/a.mp4",
                         duration_ms=3000, start_ms=0, order=0),
            TimelineClip(clip_id="c2", track=TrackKind.TEXT, source_path="/t.txt",
                         duration_ms=1000, start_ms=0, order=0),
        ),
    )


def test_timeline_projection_preserves_the_canonical_hash():
    from hevi.adapters.openreel.timeline_mapper import to_openreel_timeline

    timeline = _timeline()
    projected = to_openreel_timeline(timeline)
    assert projected.content_hash == timeline.content_hash()
    assert projected.duration_ms == timeline.duration_ms


def test_timeline_projection_is_stable_across_insertion_order():
    from hevi.adapters.openreel.timeline_mapper import to_openreel_timeline

    timeline = _timeline()
    reordered = TimelineIR(
        project_id="proj-1",
        canvas=Canvas(width=1080, height=1920, fps=30),
        clips=tuple(reversed(timeline.clips)),
    )
    assert to_openreel_timeline(reordered) == to_openreel_timeline(timeline)


# ── §12/§33 receipts ──


def test_receipt_requires_real_ffprobe_data():
    """§33/§60: no synthetic probe data. The mapper refuses rather than inventing it."""
    job = to_render_job(job_id="j", production_id="p", operation_id="o",
                        renderer="openreel", renderer_version="1",
                        width=100, height=100, fps=30, duration_ms=1000)
    artifact = OpenReelArtifact(artifact_id="a", uri="/tmp/a.mp4",
                                content_hash="ab" * 32, kind="video")
    with pytest.raises(RenderMappingError, match="WITHOUT_FFPROBE"):
        to_render_receipt(job=job, artifact=artifact, timeline_hash="th",
                          ffprobe_summary={})


def test_unhashed_artifact_cannot_become_a_reference():
    """§14 puts artifact identity inside the render identity."""
    with pytest.raises(RenderMappingError, match="WITHOUT_HASH"):
        to_artifact_ref(OpenReelArtifact(artifact_id="a", uri="/x", content_hash="",
                                        kind="video"))


def test_render_job_is_created_before_the_run():
    """§11: PLANNED at creation, so something recorded that the render was coming."""
    job = to_render_job(job_id="j", production_id="p", operation_id="o",
                        renderer="openreel", renderer_version="1",
                        width=1080, height=1920, fps=30, duration_ms=5000)
    assert job.status.value == "PLANNED"


def test_mark_succeeded_walks_the_whole_legal_state_machine():
    """PLANNED -> QUEUED -> RUNNING -> SUCCEEDED, with no skipped steps.

    An earlier version jumped straight to RUNNING and the transition table refused it.
    QUEUED matters: it is the window a crash-recovery pass reads to decide what still
    needs re-running (§58).
    """
    job = to_render_job(job_id="j", production_id="p", operation_id="o",
                        renderer="openreel", renderer_version="1",
                        width=100, height=100, fps=30, duration_ms=1000)
    assert mark_succeeded(job).status.value == "SUCCEEDED"
    with pytest.raises(ValueError):
        mark_succeeded(mark_succeeded(job))


def test_render_request_derives_everything_from_the_canonical_spec():
    job = to_render_job(job_id="j", production_id="p", operation_id="o",
                        renderer="openreel", renderer_version="1",
                        width=1080, height=1920, fps=30, duration_ms=5000)
    request = render_request(job)
    assert request["width"] == 1080
    assert request["fps_numerator"] == 30 and request["fps_denominator"] == 1
    assert request["duration_ms"] == 5000


def test_openreel_module_does_not_import_the_openreel_package():
    """§22: adapter boundary, not a core dependency.

    If this ever imports `openreel` at module scope, importing HEVI's execution contract
    starts requiring an external project, and §54's guarantee is gone.
    """
    import hevi.adapters.openreel as pkg

    source_files = list(pkg.__path__ and __import__("pathlib").Path(pkg.__path__[0]).glob("*.py"))
    for path in source_files:
        text = path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import openreel"), (
                f"{path.name} imports openreel at module scope"
            )
            assert not stripped.startswith("from openreel"), (
                f"{path.name} imports openreel at module scope"
            )
