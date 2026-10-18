"""K-G5: cascade_delete — safe source-driven KU cascade removal.

dry_run=True (default) reports without executing. Shared KUs are preserved.

db_conn expected interface:
  get_ku_ids_for_source(source_id: str) -> list[str]    (async or sync)
  get_source_ids_for_ku(ku_id: str) -> list[str]         (async or sync)
  delete_ku(ku_id: str) -> None                          (async or sync)
  get_dangling_deps_count(ku_id: str) -> int             (async or sync)
  clear_dangling_deps(ku_id: str) -> None                (async or sync)
"""

from __future__ import annotations

import inspect
from typing import Any

from oprim._aii_graph_types import CascadeDeleteResult


async def cascade_delete(
    *,
    source_id: str,
    db_conn: Any,
    dry_run: bool = True,
) -> CascadeDeleteResult:
    """Cascade-delete KUs that are exclusively supported by source_id.

    dry_run=True (default): report only, do not modify data.
    Shared KUs (supported by other sources) are always preserved.
    """
    # Find all KUs associated with this source
    ku_ids = await _call(db_conn.get_ku_ids_for_source, source_id)

    deleted: list[str] = []
    preserved: list[str] = []
    dangling_cleared = 0

    for ku_id in ku_ids:
        # Check if this KU has other sources
        all_sources = await _call(db_conn.get_source_ids_for_ku, ku_id)
        other_sources = [s for s in all_sources if s != source_id]

        if other_sources:
            # Shared KU — preserve
            preserved.append(ku_id)
            continue

        # Exclusive KU — delete (or report)
        dep_count = 0
        try:
            dep_count = await _call(db_conn.get_dangling_deps_count, ku_id)
        except Exception:
            dep_count = 0

        if not dry_run:
            try:
                await _call(db_conn.clear_dangling_deps, ku_id)
                await _call(db_conn.delete_ku, ku_id)
            except Exception:
                pass

        dangling_cleared += dep_count
        deleted.append(ku_id)

    return CascadeDeleteResult(
        deleted_ku_ids=deleted,
        preserved_ku_ids=preserved,
        dangling_deps_cleared=dangling_cleared,
        dry_run=dry_run,
    )


async def _call(fn, *args):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
