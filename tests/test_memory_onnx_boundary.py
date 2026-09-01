from __future__ import annotations

from pathlib import Path

from hevi.memory.store import MemoryStore


def test_memory_summary_consolidation_is_local_and_recallable(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.remember("short_term", "episode-1", {"verdict": "passed", "shots": 4})
    summary_id = store.consolidate_summary("episode-1")
    assert summary_id > 0
    hit = store.by_key("episode-1", limit=1)[0]
    assert hit.kind == "summary"
    assert hit.payload["source_count"] == 1


def test_onnx_embedder_reports_missing_local_model(tmp_path: Path) -> None:
    from hevi.memory.store import OnnxEmbedder

    embedder = OnnxEmbedder(tmp_path / "missing.onnx", lambda _text: {})
    try:
        embedder.embed("query")
    except FileNotFoundError as exc:
        assert "ONNX memory model not found" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("missing ONNX model must not be treated as available")
