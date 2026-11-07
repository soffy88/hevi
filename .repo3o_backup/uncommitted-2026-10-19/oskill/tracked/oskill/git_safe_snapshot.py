"""K-14 git_safe_snapshot — create a recoverable git snapshot (undo support).

Composes oprim:
    - git_current_branch
    - git_snapshot
    - parse_git_status
    - obase.git.run_git

IO-orchestration (git commands). obase.git.run_git available in obase v0.15.1.
"""

from __future__ import annotations

from pathlib import Path

from oprim import git_current_branch, git_snapshot, parse_git_status

from ._hc_types import SnapshotId


async def git_safe_snapshot(repo: Path) -> SnapshotId:
    """Create a recoverable snapshot of the repository state.

    Composes: git_current_branch, git_snapshot, parse_git_status,
              obase.git.run_git.

    Args:
        repo: Repository root.

    Returns:
        SnapshotId string (commit sha or empty if clean).

    Raises:
        RuntimeError: If not a git repository.
    """
    from obase.git import run_git

    # Verify repo
    try:
        await run_git(["rev-parse", "--git-dir"], cwd=repo)
    except Exception as exc:
        raise RuntimeError(f"Not a git repository: {repo}") from exc

    # Get current branch and status
    await git_current_branch(repo)
    status = await parse_git_status(repo)

    # Check if there are changes to snapshot
    has_changes = bool(
        getattr(status, "modified", [])
        or getattr(status, "added", [])
        or getattr(status, "deleted", [])
        or getattr(status, "untracked", [])
    )

    if not has_changes:
        # Clean working tree: return HEAD sha as snapshot id
        try:
            result = await run_git(["rev-parse", "HEAD"], cwd=repo)
            return str(result).strip() if result else ""
        except Exception:
            return ""

    # Stash untracked and changes
    snapshot_id = await git_snapshot(repo)

    return str(snapshot_id) if snapshot_id else ""
