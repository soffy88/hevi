"""oskill.sync.flush_outbox — upload local changefeed events to remote storage."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from oprim._logging import log
from oprim.changefeed.reader import ChangefeedReader
from oprim.meta_db.duckdb import MetaDB

from oskill.sync.errors import FlushError

_DEFAULT_STATE_DIR = Path.home() / ".stratum"


@dataclass
class FlushResult:
    flushed_count: int
    failed_count: int
    last_flushed_seq: int
    uploaded_files: list[str] = field(default_factory=list)


def _state_path(user_id: str, device_id: str, state_dir: Path) -> Path:
    return state_dir / f"sync_state_{user_id}_{device_id}.json"


def _load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


async def flush_outbox(
    user_id: str,
    device_id: str,
    db: MetaDB,
    storage_adapter,
    *,
    batch_size: int = 500,
    state_dir: Path | None = None,
) -> FlushResult:
    """Upload all unflushed local changefeed events to remote storage.

    Reads events written by this device from the local DB and uploads them as
    JSONL to:  /Stratum/changefeed/{device_id}/events_{seq_start}_{seq_end}.jsonl

    State (last_flushed_seq) is persisted to
    ~/.stratum/sync_state_{user_id}_{device_id}.json so subsequent calls only
    upload new events.
    """
    state_dir = state_dir or _DEFAULT_STATE_DIR
    state_file = _state_path(user_id, device_id, state_dir)
    state = _load_state(state_file)
    last_flushed_seq: int = int(state.get("last_flushed_seq", 0))

    reader = ChangefeedReader(db, user_id)
    events = reader.read_since(last_flushed_seq, batch_size=batch_size)

    # Only upload events originating from this device
    own_events = [e for e in events if e.device_id == device_id]

    # Advance seq pointer even if no own events (avoids re-reading remote events)
    latest_seq = events[-1].seq if events else last_flushed_seq

    if not own_events:
        log.info("flush_outbox_no_own_events", user_id=user_id, device_id=device_id)
        if latest_seq != last_flushed_seq:
            state["last_flushed_seq"] = latest_seq
            _save_state(state_file, state)
        return FlushResult(
            flushed_count=0,
            failed_count=0,
            last_flushed_seq=latest_seq,
        )

    seq_start = own_events[0].seq
    seq_end = own_events[-1].seq

    jsonl_lines = [json.dumps(e.to_dict(), ensure_ascii=False) for e in own_events]
    jsonl_content = "\n".join(jsonl_lines)

    remote_path = f"Stratum/changefeed/events_{device_id}_{seq_start}_{seq_end}.jsonl"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(jsonl_content)
        tmp_path = tf.name

    try:
        await storage_adapter.upload(
            tmp_path,
            remote_path,
            mime_type="application/x-ndjson",
        )
    except Exception as exc:
        log.error("flush_outbox_upload_failed", error=str(exc), remote_path=remote_path)
        raise FlushError(f"Upload failed for {remote_path}: {exc}") from exc
    finally:
        os.unlink(tmp_path)

    state["last_flushed_seq"] = seq_end
    _save_state(state_file, state)

    log.info(
        "flush_outbox_done",
        flushed=len(own_events),
        last_seq=seq_end,
        remote_path=remote_path,
        user_id=user_id,
    )
    return FlushResult(
        flushed_count=len(own_events),
        failed_count=0,
        last_flushed_seq=seq_end,
        uploaded_files=[remote_path],
    )
