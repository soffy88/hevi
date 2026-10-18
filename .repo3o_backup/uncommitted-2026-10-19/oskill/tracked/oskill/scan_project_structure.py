"""K-13 scan_project_structure — scan repo structure for AGENTS.md generation.

Composes oprim:
    - dir_list
    - detect_project_type
    - glob_match
    - parse_gitignore
    - apply_gitignore

IO-orchestration (dir listing). Stateless.
"""

from __future__ import annotations

from pathlib import Path

from oprim import apply_gitignore, detect_project_type, dir_list, glob_match, parse_gitignore

from ._hc_types import ProjectMap

_KEY_FILE_PATTERNS = [
    "*.toml",
    "*.json",
    "Makefile",
    "Dockerfile",
    "*.yaml",
    "*.yml",
    "*.md",
    "*.cfg",
    "*.ini",
    "setup.py",
    "requirements*.txt",
    "go.mod",
    "package.json",
    "Cargo.toml",
    "*.gradle",
]


async def scan_project_structure(
    root: Path,
    *,
    max_depth: int = 4,
) -> ProjectMap:
    """Scan project directory structure and detect type and key files.

    Composes: dir_list, detect_project_type, glob_match,
              parse_gitignore, apply_gitignore.

    Args:
        root: Repository root.
        max_depth: Maximum directory depth to scan (default 4).

    Returns:
        ProjectMap with project_type, key_files, tree lines, languages.
    """
    if not root.exists():
        raise FileNotFoundError(f"root does not exist: {root}")

    # Load gitignore
    patterns = []
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        patterns = parse_gitignore(gitignore_path)

    # Detect project type
    try:
        project_type_result = await detect_project_type(root)
        project_type = str(project_type_result) if project_type_result else "unknown"
    except Exception:
        project_type = "unknown"

    # List directory tree
    try:
        all_entries = await dir_list(root, max_depth=max_depth)
    except Exception:
        all_entries = []

    # Apply gitignore filter
    if patterns and all_entries:
        all_paths = [Path(str(e)) for e in all_entries]
        filtered = apply_gitignore(all_paths, patterns=patterns, root=root)
        filtered_set = {str(p) for p in filtered}
        all_entries = [e for e in all_entries if str(e) in filtered_set]

    # Build tree lines (simple indented format)
    tree: list[str] = []
    for entry in all_entries[:200]:  # limit for performance
        p = Path(str(entry))
        try:
            rel = p.relative_to(root)
            depth = len(rel.parts) - 1
            indent = "  " * depth
            tree.append(f"{indent}{p.name}{'/' if p.is_dir() else ''}")
        except ValueError:
            tree.append(str(p.name))

    # Identify key files
    key_files: list[str] = []
    for pattern in _KEY_FILE_PATTERNS:
        try:
            matches = await glob_match(root, pattern=pattern)
            for m in matches[:3]:
                rel = Path(str(m)).relative_to(root)
                if str(rel) not in key_files:
                    key_files.append(str(rel))
        except Exception:
            pass

    # Languages from project_type
    languages: list[str] = []
    pt_lower = project_type.lower()
    for lang in ("python", "go", "javascript", "typescript", "rust", "java", "kotlin", "ruby"):
        if lang in pt_lower:
            languages.append(lang)

    return ProjectMap(
        root=root,
        project_type=project_type,
        key_files=key_files,
        tree=tree,
        languages=languages,
    )
