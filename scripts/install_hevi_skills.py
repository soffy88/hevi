#!/usr/bin/env python3
"""hevi agent skills 安装器 —— 把 hevi/skills/* 安装进宿主 agent skills 目录。

仿 claude-video 的跨宿主安装:把每个技能目录(含 SKILL.md + scripts)软链进
宿主 skills 目录。宿主按环境变量探测:CLAUDE_SKILLS_DIR / CODEX_SKILLS_DIR /
AGENTS_SKILLS_DIR;缺省 ~/.claude/skills、~/.codex/skills、~/.agents/skills。

用法:
    python scripts/install_hevi_skills.py [--host claude|codex|agents|all] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_SRC = REPO_ROOT / "hevi" / "skills"
SKILL_DIRS = (
    "hevi-watch",
    "hevi-media",
    "hevi-promo",
    "hevi-story",
    "hevi-interactive",
    "hevi-studio",
    "hevi-hyperframes",
    "hevi-daily",
)

_HOST_DIRS = {
    "claude": ("CLAUDE_SKILLS_DIR", Path("~/.claude/skills")),
    "codex": ("CODEX_SKILLS_DIR", Path("~/.codex/skills")),
    "agents": ("AGENTS_SKILLS_DIR", Path("~/.agents/skills")),
}


def resolve_host_dir(host: str) -> Path:
    env_key, default = _HOST_DIRS[host]
    env_val = os.environ.get(env_key)
    if env_val:
        return Path(env_val).expanduser()
    return Path.home() / str(default).replace("~", "").lstrip("/")


def install(host: str, *, dry_run: bool) -> list[tuple[str, Path, bool]]:
    """安装一个宿主;返回 [(skill, target, created)]。"""
    target_root = resolve_host_dir(host)
    result: list[tuple[str, Path, bool]] = []
    for skill in SKILL_DIRS:
        src = SKILLS_SRC / skill
        if not (src / "SKILL.md").exists():
            raise FileNotFoundError(f"skill missing SKILL.md: {src}")
        target = target_root / skill
        if target.exists() and target.is_symlink():
            result.append((skill, target, False))  # 已装
            continue
        if dry_run:
            result.append((skill, target, True))
            continue
        target_root.mkdir(parents=True, exist_ok=True)
        target.symlink_to(src)
        result.append((skill, target, True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=[*_HOST_DIRS.keys(), "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="只列出将安装的目标")
    args = parser.parse_args(argv)

    hosts = list(_HOST_DIRS) if args.host == "all" else [args.host]
    for host in hosts:
        for skill, target, created in install(host, dry_run=args.dry_run):
            mark = (
                "would install"
                if args.dry_run
                else ("installed" if created else "already linked")
            )
            print(f"[{host}] {skill} -> {target} ({mark})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
