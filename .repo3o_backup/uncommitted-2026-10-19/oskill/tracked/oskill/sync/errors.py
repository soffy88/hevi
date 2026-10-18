"""Sync-specific errors."""

from __future__ import annotations

from oprim.errors import StratumError


class SyncError(StratumError):
    """Base class for sync-related errors."""


class FlushError(SyncError):
    """Failed to flush local outbox to remote storage."""


class ApplyError(SyncError):
    """Failed to apply remote events to local DB."""


class SnapshotError(SyncError):
    """Snapshot create or restore failed."""


class ConflictResolutionError(SyncError):
    """Could not resolve a conflicting event (last-write-wins failed)."""
