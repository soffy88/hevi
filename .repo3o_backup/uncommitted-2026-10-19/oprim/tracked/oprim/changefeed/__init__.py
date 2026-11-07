"""oprim.changefeed — append-only event log for Stratum multi-device sync (Phase 2).

Restored from Phase 2 Wave 2 (commit 11a6f0b). Canonical contract:
event_type / seq / device_id on ChangefeedEvent, dotted EventType values.

Engine/recovery primitives only — no business/project state, no sibling imports.
"""

from __future__ import annotations

from oprim.changefeed.errors import (
    ChangefeedConflictError,
    ChangefeedError,
)
from oprim.changefeed.reader import ChangefeedReader
from oprim.changefeed.schema import ChangefeedEvent, EventType
from oprim.changefeed.snapshot import ChangefeedSnapshot
from oprim.changefeed.writer import ChangefeedWriter

__all__ = [
    "ChangefeedWriter",
    "ChangefeedReader",
    "ChangefeedSnapshot",
    "ChangefeedEvent",
    "EventType",
    "ChangefeedError",
    "ChangefeedConflictError",
]
