"""Tests for pipeline.preview_tasks: originals, previews, task states."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.preview_tasks import (
    create_task,
    generate_preview,
    get_task,
    list_tasks,
    retry_task,
    run_preview_task,
    run_task,
    store_original,
)
from hevi.capabilities.registry import get


def _store(tmp_path: Path) -> Path:
    return tmp_path / "task_store.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_preview(original: Path, preview: Path) -> None:
    preview.write_bytes(b"preview-of-" + original.read_bytes()[:8])


def test_capability_registered() -> None:
    assert get("pipeline.preview_tasks").name == "pipeline.preview_tasks"


def test_store_original_is_verbatim_not_transcoded(tmp_path: Path) -> None:
    source = tmp_path / "master.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypfake-hevc-bytes")
    stored = store_original(source, tmp_path / "vault" / "master.mp4")
    assert stored["transcoded"] is False
    assert stored["sha256"] == _sha(source)
    assert (tmp_path / "vault" / "master.mp4").read_bytes() == source.read_bytes()


def test_store_original_missing_source_refused(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="not found"):
        store_original(tmp_path / "nope.mp4", tmp_path / "out.mp4")


def test_preview_success_leaves_original_untouched(tmp_path: Path) -> None:
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"original-bytes-1234")
    before = _sha(original)
    info = generate_preview(original, tmp_path / "prev.mp4",
                            preview_fn=_copy_preview)
    assert info["original_unchanged"] is True
    assert info["original_sha256_before"] == before
    assert info["original_sha256_after"] == before
    assert _sha(original) == before
    assert (tmp_path / "prev.mp4").is_file()


def test_preview_failure_leaves_original_and_no_preview(tmp_path: Path) -> None:
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"original-bytes-1234")
    before = _sha(original)

    def _boom(_o: Path, preview: Path) -> None:
        preview.write_bytes(b"partial")
        raise RuntimeError("encoder exploded")

    with pytest.raises(CapabilityError, match="preview generation failed"):
        generate_preview(original, tmp_path / "prev.mp4", preview_fn=_boom)
    assert _sha(original) == before
    assert not (tmp_path / "prev.mp4").exists()


def test_preview_refuses_to_overwrite_original(tmp_path: Path) -> None:
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"original-bytes")
    with pytest.raises(CapabilityError, match="must differ"):
        generate_preview(original, original, preview_fn=_copy_preview)


def test_previews_are_single_threaded_not_parallel(tmp_path: Path) -> None:
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"original-bytes")
    started = threading.Event()
    release = threading.Event()
    outcomes: list[str] = []

    def _slow(_o: Path, preview: Path) -> None:
        started.set()
        assert release.wait(timeout=10)
        preview.write_bytes(b"slow-preview")

    def _run_second() -> None:
        assert started.wait(timeout=10)
        try:
            generate_preview(original, tmp_path / "prev2.mp4",
                             preview_fn=_copy_preview)
            outcomes.append("ran")
        except CapabilityError as exc:
            outcomes.append(str(exc))

    worker = threading.Thread(target=lambda: generate_preview(
        original, tmp_path / "prev1.mp4", preview_fn=_slow))
    worker.start()
    second = threading.Thread(target=_run_second)
    second.start()
    second.join(timeout=15)
    release.set()
    worker.join(timeout=15)
    assert len(outcomes) == 1
    assert "preview already running" in outcomes[0]
    assert (tmp_path / "prev1.mp4").is_file()
    assert not (tmp_path / "prev2.mp4").exists()


def test_task_state_machine_and_invalid_transitions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    create_task(store, task_id="t1", input_snapshot={"src": "a.mp4"})
    assert get_task(store, "t1")["status"] == "queued"
    with pytest.raises(CapabilityError, match="only failed tasks may retry"):
        retry_task(store, task_id="t1")
    done = run_task(store, task_id="t1", worker_fn=lambda snap: {"ok": snap})
    assert done["status"] == "completed"
    assert done["result"] == {"ok": {"src": "a.mp4"}}
    with pytest.raises(CapabilityError, match="cannot start from status"):
        run_task(store, task_id="t1", worker_fn=lambda snap: None)


def test_failed_task_keeps_snapshot_reason_and_record_then_retries(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = {"src": "a.mp4", "trim": [1, 2]}
    create_task(store, task_id="t1", input_snapshot=snapshot)
    snapshot["src"] = "mutated-after-create.mp4"
    failed = run_task(store, task_id="t1",
                      worker_fn=lambda snap: (_ for _ in ()).throw(
                          RuntimeError("disk full")))
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "disk full"
    assert failed["input_snapshot"] == {"src": "a.mp4", "trim": [1, 2]}
    assert len(failed["attempts"]) == 1
    retried = retry_task(store, task_id="t1")
    assert retried["status"] == "queued"
    assert retried["failure_reason"] == "disk full"
    assert retried["input_snapshot"] == {"src": "a.mp4", "trim": [1, 2]}
    assert len(retried["attempts"]) == 1
    done = run_task(store, task_id="t1", worker_fn=lambda snap: {"ok": True})
    assert done["status"] == "completed"
    assert get_task(store, "t1")["status"] == "completed"


def test_task_record_is_never_dropped_on_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    create_task(store, task_id="t1")
    run_task(store, task_id="t1",
             worker_fn=lambda snap: (_ for _ in ()).throw(ValueError("bad")))
    assert [t["task_id"] for t in list_tasks(store)] == ["t1"]
    assert [t["task_id"] for t in list_tasks(store, status="failed")] == ["t1"]


def test_duplicate_task_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    create_task(store, task_id="t1")
    with pytest.raises(CapabilityError, match="already exists"):
        create_task(store, task_id="t1")


def test_preview_task_end_to_end_with_stub(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = tmp_path / "orig.mp4"
    original.write_bytes(b"original-bytes-xyz")
    before = _sha(original)
    create_task(store, task_id="p1", kind="preview",
                input_snapshot={"original": str(original)})
    done = run_preview_task(store, task_id="p1", original_path=original,
                            preview_path=tmp_path / "prev.mp4",
                            preview_fn=_copy_preview)
    assert done["status"] == "completed"
    assert done["result"]["original_unchanged"] is True
    assert _sha(original) == before
    assert (tmp_path / "prev.mp4").is_file()


def test_real_ffmpeg_hevc_original_to_h264_preview(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not on PATH")
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True,
                              timeout=60).stdout
    if "libx265" not in encoders or "libx264" not in encoders:
        pytest.skip("libx265/libx264 encoders unavailable")
    original = tmp_path / "orig_hevc.mp4"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=64x64:rate=10",
         "-c:v", "libx265", "-pix_fmt", "yuv420p", str(original)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    before = _sha(original)
    info = generate_preview(original, tmp_path / "prev_h264.mp4")
    assert info["original_unchanged"] is True
    assert _sha(original) == before
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "json",
         str(tmp_path / "prev_h264.mp4")],
        capture_output=True, text=True, timeout=60).stdout)
    assert probe["streams"][0]["codec_name"] == "h264"
    probe_orig = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "json",
         str(original)],
        capture_output=True, text=True, timeout=60).stdout)
    assert probe_orig["streams"][0]["codec_name"] == "hevc"


def test_registry_render_create_and_list(tmp_path: Path) -> None:
    store = str(_store(tmp_path))
    out = tmp_path / "out"
    created = caps.get("pipeline.preview_tasks").render(
        {"store_path": store, "action": "create", "task_id": "t1",
         "input_snapshot": {"src": "a.mp4"}},
        out, duration=0.0, aspect="16:9", seed=1)
    assert created.qa["result"]["record"]["status"] == "queued"
    listed = caps.get("pipeline.preview_tasks").render(
        {"store_path": store, "action": "list"},
        out, duration=0.0, aspect="16:9", seed=1)
    assert [t["task_id"] for t in listed.qa["result"]["tasks"]] == ["t1"]
