"""oskill.sync — multi-device sync skills for Stratum (Phase 2)."""

from oskill.sync.apply_remote_events import SyncApplyResult, apply_remote_events
from oskill.sync.errors import (
    ApplyError,
    ConflictResolutionError,
    FlushError,
    SnapshotError,
    SyncError,
)
from oskill.sync.flush_outbox import FlushResult, flush_outbox
from oskill.sync.restore_from_snapshot import restore_from_snapshot
from oskill.sync.snapshot_backup import snapshot_backup

__all__ = [
    "flush_outbox",
    "FlushResult",
    "apply_remote_events",
    "SyncApplyResult",
    "snapshot_backup",
    "restore_from_snapshot",
    "SyncError",
    "FlushError",
    "ApplyError",
    "SnapshotError",
    "ConflictResolutionError",
]
