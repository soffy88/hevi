"""Auto-split from hicode whl."""

from __future__ import annotations

from typing import Any

from ._types import UndoPlan


def build_undo_plan(
    changeset: dict[str, Any],
    *,
    snapshot_rev: str,
) -> UndoPlan:
    """根据 changeset 元数据构建 undo 计划（纯内存）。

    组合：路径提取 + snapshot_rev 绑定 + 描述生成。
    实际 undo 执行由 Layer 4 + obase.versionstore 完成，
    oskill 只负责"计划"这个纯计算步骤。

    Args:
        changeset: apply_changeset 返回的 dict（含 applied / fingerprint 等）。
        snapshot_rev: versionstore 快照 rev（apply_changeset 返回的）。

    Returns:
        UndoPlan(snapshot_rev, paths, description, can_undo)。

    Example:
        >>> plan = build_undo_plan({"applied": ["a.py", "b.py"]}, snapshot_rev="rev1")
        >>> plan.can_undo
        True
        >>> plan.paths
        ['a.py', 'b.py']
    """
    applied = changeset.get("applied", [])
    status = changeset.get("status", "completed")
    fingerprint = changeset.get("fingerprint", "")

    can_undo = bool(snapshot_rev) and status in ("completed",)
    n = len(applied)
    description = (
        f"Undo {n} file{'s' if n != 1 else ''} "
        f"(fingerprint={fingerprint[:8] or 'n/a'}, rev={snapshot_rev[:8] or 'n/a'})"
    )

    return UndoPlan(
        snapshot_rev=snapshot_rev,
        paths=list(applied),
        description=description,
        can_undo=can_undo,
    )
