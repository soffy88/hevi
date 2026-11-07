"""K-12 worktree_prepare — create or reuse a git worktree for isolated sessions.

Composes oprim:
    - git_current_branch
    - git_snapshot
    - obase.git.run_git (for worktree add)

IO-orchestration (git commands). obase.git.run_git is available in obase v0.15.1.
"""

from __future__ import annotations

from pathlib import Path


async def worktree_prepare(repo: Path, *, branch: str) -> Path:
    """Prepare a git worktree on *branch* under *repo*.

    Composes: git_current_branch (oprim), git_snapshot (oprim),
              obase.git.run_git (worktree operations).

    Args:
        repo: Repository root.
        branch: Target branch name.

    Returns:
        Path to the prepared worktree.

    Raises:
        ValueError: If branch is empty.
        RuntimeError: If repo is not a git repository.
    """
    if not branch:
        raise ValueError("branch must not be empty")

    from obase.git import run_git  # obase v0.15.1
    from oprim import git_snapshot

    # Verify repo is a git repo
    try:
        await run_git(["rev-parse", "--git-dir"], cwd=repo)
    except Exception as exc:
        raise RuntimeError(f"Not a git repository: {repo}") from exc

    # Take snapshot of current state
    await git_snapshot(repo)

    # Check if worktree for this branch already exists
    wt_list_result = await run_git(["worktree", "list", "--porcelain"], cwd=repo)
    wt_lines = str(wt_list_result).splitlines() if isinstance(wt_list_result, str) else []

    existing_wt: Path | None = None
    i = 0
    current_wt_path: str | None = None
    while i < len(wt_lines):
        line = wt_lines[i]
        if line.startswith("worktree "):
            current_wt_path = line.split(" ", 1)[1].strip()
        elif line.startswith("branch ") and current_wt_path:
            wt_branch = line.split("refs/heads/", 1)[-1].strip()
            if wt_branch == branch and current_wt_path != str(repo):
                existing_wt = Path(current_wt_path)
        i += 1

    if existing_wt is not None:
        return existing_wt

    # Create new worktree
    wt_path = repo.parent / f".worktrees/{repo.name}-{branch}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    # Check if branch exists
    try:
        await run_git(["rev-parse", "--verify", branch], cwd=repo)
        # Branch exists: add worktree
        await run_git(["worktree", "add", str(wt_path), branch], cwd=repo)
    except Exception:
        # Branch doesn't exist: create it
        await run_git(["worktree", "add", "-b", branch, str(wt_path)], cwd=repo)

    return wt_path
