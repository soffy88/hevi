"""P5 editable project delivery unit tests."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from hevi.ops.p5_types import (
    ContentItem,
    ContentRequest,
    ContentStatus,
    BookSourceBundle,
    EditableProjectManifest,
    CaptionStyleProfile,
    VoicePerformance,
    VoiceProfile,
)
from hevi.ops.p5_editable import (
    JianyingDraftBuilder,
    JianyingSegment,
    JianyingMaterial,
    _sha256_file,
    validate_jianying_draft,
    validate_editable_delivery,
)


def test_jianying_builder_basic(tmp_path) -> None:
    builder = JianyingDraftBuilder(tmp_path)
    # Create a fake video file
    test_file = tmp_path / "test.mp4"
    test_file.write_bytes(b"fake video")
    mat_id = builder.add_video_material(test_file, "abc123")
    assert mat_id.startswith("video_")

    # Create a segment
    seg = JianyingSegment(
        segment_id="seg1",
        material_id=mat_id,
        target_timerange={"start": 0, "duration": 1000000},
        source_timerange={"start": 0, "duration": 1000000},
    )
    builder.create_video_track([seg])

    draft_dir = builder.save()
    assert draft_dir.exists()
    assert (draft_dir / "draft_content.json").exists()
    assert (draft_dir / "draft_info.json").exists()


def test_validate_jianying_draft(tmp_path) -> None:
    builder = JianyingDraftBuilder(tmp_path)
    # Add a fake material that exists
    test_file = tmp_path / "test.mp4"
    test_file.write_bytes(b"fake video")
    mat_id = builder.add_video_material(test_file)
    seg = JianyingSegment(
        segment_id="seg1",
        material_id=mat_id,
        target_timerange={"start": 0, "duration": 1000000},
        source_timerange={"start": 0, "duration": 1000000},
    )
    builder.create_video_track([seg])
    draft_dir = builder.save()

    valid, errors = validate_jianying_draft(draft_dir)
    assert valid, f"errors: {errors}"


def test_validate_jianying_draft_missing_material(tmp_path) -> None:
    builder = JianyingDraftBuilder(tmp_path)
    # Create draft with material that doesn't exist
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    draft_content = {
        "version": "2.0.0",
        "draft_id": "test",
        "materials": [{"material_id": "video_1", "type": "video", "path": "/nonexistent.mp4", "duration": 1000000}],
        "tracks": [{"track_id": "t1", "track_type": "video", "segments": [{"segment_id": "s1", "material_id": "video_1", "target_timerange": {"start": 0, "duration": 1000000}}]}],
        "canvas_config": {"width": 1280, "height": 720},
        "duration": 1000000,
        "fps": 30,
    }
    (draft_dir / "draft_content.json").write_text(json.dumps(draft_content))

    valid, errors = validate_jianying_draft(draft_dir)
    assert not valid
    assert any("missing" in e for e in errors)


def test_editable_manifest_validation(tmp_path) -> None:
    # Create a minimal valid editable project
    test_file = tmp_path / "test.wav"
    test_file.write_bytes(b"audio")
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    draft_content = {
        "version": "2.0.0",
        "draft_id": "test",
        "materials": [{"material_id": "audio_1", "type": "audio", "path": str(test_file), "duration": 1000000}],
        "tracks": [{"track_id": "t1", "track_type": "audio", "segments": [{"segment_id": "s1", "material_id": "audio_1", "target_timerange": {"start": 0, "duration": 1000000}}]}],
        "canvas_config": {"width": 1280, "height": 720},
        "duration": 1000000,
        "fps": 30,
    }
    (draft_dir / "draft_content.json").write_text(json.dumps(draft_content))

    manifest = EditableProjectManifest(
        project_type="jianying",
        project_path=str(draft_dir),
        duration_s=1.0,
        audio_refs=[str(test_file)],
    )
    valid, errors = validate_editable_delivery(manifest)
    assert valid, f"errors: {errors}"


def test_editable_manifest_missing_audio_ref(tmp_path) -> None:
    # Create a valid draft directory first
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    test_file = tmp_path / "test.wav"
    test_file.write_bytes(b"audio")
    draft_content = {
        "version": "2.0.0",
        "draft_id": "test",
        "materials": [{"material_id": "audio_1", "type": "audio", "path": str(test_file), "duration": 1000000}],
        "tracks": [{"track_id": "t1", "track_type": "audio", "segments": [{"segment_id": "s1", "material_id": "audio_1", "target_timerange": {"start": 0, "duration": 1000000}}]}],
        "canvas_config": {"width": 1280, "height": 720},
        "duration": 1000000,
        "fps": 30,
    }
    (draft_dir / "draft_content.json").write_text(json.dumps(draft_content))

    manifest = EditableProjectManifest(
        project_type="jianying",
        project_path=str(draft_dir),
        duration_s=1.0,
        audio_refs=[str(test_file), "/nonexistent/audio.wav"],
    )
    valid, errors = validate_editable_delivery(manifest)
    assert not valid
    assert any("missing" in e for e in errors)


def test_editable_manifest_missing_project_path(tmp_path) -> None:
    manifest = EditableProjectManifest(
        project_type="jianying",
        project_path="",
        duration_s=1.0,
    )
    valid, errors = validate_editable_delivery(manifest)
    assert not valid
    assert any("project_path" in e for e in errors)


def test_sha256_file(tmp_path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    hash_val = _sha256_file(test_file)
    assert len(hash_val) == 64
    assert hash_val == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_content_item_editable_validation(tmp_path) -> None:
    # Create a content item with editable project
    test_file = tmp_path / "test.wav"
    test_file.write_bytes(b"audio")
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    draft_content = {
        "version": "2.0.0",
        "draft_id": "test",
        "materials": [{"material_id": "audio_1", "type": "audio", "path": str(test_file), "duration": 1000000}],
        "tracks": [{"track_id": "t1", "track_type": "audio", "segments": [{"segment_id": "s1", "material_id": "audio_1", "target_timerange": {"start": 0, "duration": 1000000}}]}],
        "canvas_config": {"width": 1280, "height": 720},
        "duration": 1000000,
        "fps": 30,
    }
    (draft_dir / "draft_content.json").write_text(json.dumps(draft_content))

    item = ContentItem(
        content_id="test",
        request=ContentRequest(
            topic="Test",
            profile_id="EMOTIONAL_BOOK_REVIEW",
            book_source=BookSourceBundle(book_title="B", author="A", verified_facts=["f"]),
        ),
    )
    item.editable_project = EditableProjectManifest(
        project_type="jianying",
        project_path=str(draft_dir),
        duration_s=1.0,
        audio_refs=[str(test_file)],
    )
    item.status = ContentStatus.FINAL_RENDER

    # Test validation
    valid, errors = validate_editable_delivery(item.editable_project)
    assert valid, f"errors: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])