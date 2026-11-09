"""CC0-only asset source adapter around ``sozai-search-mcp`` (MIT).

Only assets whose record says ``CC0-1.0`` (or ``redistributable: true``) are
accepted automatically.  Every fetch writes a CREDITS.md line, stays under the
5 GiB cache ceiling, and refuses a single file over 300 MiB.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = [
    "CC0_LICENCES",
    "MAX_CACHE_BYTES",
    "MAX_FILE_BYTES",
    "AssetRejected",
    "CacheFull",
    "SozaiUnavailable",
    "cache_dir",
    "cache_size",
    "fetch_cc0",
]

CC0_LICENCES = {"cc0-1.0", "cc0", "public-domain", "public_domain", "pd"}
MAX_CACHE_BYTES = 5 * 1024**3
MAX_FILE_BYTES = 300 * 1024**2


class SozaiUnavailable(RuntimeError):
    pass


class AssetRejected(ValueError):
    pass


class CacheFull(RuntimeError):
    pass


def cache_dir(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("HEVI_ASSETS3D", "/data/soffy/assets3d"))


def cache_size(root: str | Path | None = None) -> int:
    base = cache_dir(root)
    if not base.exists():
        return 0
    return sum(p.stat().st_size for p in base.rglob("*") if p.is_file())


def _runner_default(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


def _parse_record(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            return record
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_cc0(record: dict[str, Any]) -> bool:
    licence = str(record.get("licence") or record.get("license") or "").strip().lower()
    return licence in CC0_LICENCES or bool(record.get("redistributable"))


def _find_payload(record: dict[str, Any], target: Path) -> Path | None:
    raw = str(record.get("path") or record.get("file") or "")
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = target / candidate
        if candidate.is_file():
            return candidate
    files = [p for p in target.rglob("*") if p.is_file() and p.name not in {"CREDITS.md", "asset.json"}]
    return max(files, key=lambda p: p.stat().st_size) if files else None


def fetch_cc0(
    asset_id: str,
    *,
    root: str | Path | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    sozai_src: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch one CC0 asset; returns its record with ``path`` and ``credits``.

    The caller may inject ``runner`` for tests.  When the sozai package is not
    importable the function raises :class:`SozaiUnavailable` — it never reports a
    fake success.
    """
    base = cache_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    target = base / "sozai" / str(asset_id).replace(":", "_")
    target.mkdir(parents=True, exist_ok=True)

    src = str(sozai_src or os.environ.get("HEVI_SOZAI_SRC") or "")
    env_prefix: list[str] = []
    cmd: list[str]
    if src:
        env_prefix = ["env", f"PYTHONPATH={src}"]
        cmd = [*env_prefix, "python3", "-m", "sozai", "fetch", asset_id, str(target)]
    else:
        cmd = ["sozai", "fetch", asset_id, str(target)]
    runner = runner or _runner_default
    try:
        proc = runner(cmd)
    except FileNotFoundError as exc:
        raise SozaiUnavailable(
            "sozai CLI not found; set HEVI_SOZAI_SRC to the package src or install sozai"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SozaiUnavailable("sozai fetch timed out after 180s") from exc
    if proc.returncode != 0:
        raise SozaiUnavailable(
            f"sozai fetch failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-300:]}"
        )

    record = _parse_record(proc.stdout or "")
    if not record:
        record_path = target / "asset.json"
        if record_path.is_file():
            record = json.loads(record_path.read_text(encoding="utf-8"))
    if not _is_cc0(record):
        raise AssetRejected(
            f"asset {asset_id} is not CC0/redistributable: {record.get('licence')!r}"
        )
    payload = _find_payload(record, target)
    if payload is None:
        raise SozaiUnavailable(f"sozai reported success but produced no file for {asset_id}")
    size = payload.stat().st_size
    if size > MAX_FILE_BYTES:
        raise AssetRejected(f"{payload.name} is {size} bytes > 300 MiB ceiling")
    if cache_size(base) + size > MAX_CACHE_BYTES:
        raise CacheFull(
            f"assets3d cache would exceed 5 GiB (now {cache_size(base)} + {size})"
        )

    credit_line = (
        f"- `{asset_id}` — {payload.name} — "
        f"{record.get('licence') or 'CC0-1.0'} — "
        f"{record.get('source') or record.get('provider') or 'sozai'}\n"
    )
    credits = base / "CREDITS.md"
    existing = credits.read_text(encoding="utf-8") if credits.is_file() else "# 3D asset credits\n\n"
    if credit_line not in existing:
        credits.write_text(existing + credit_line, encoding="utf-8")
    record = {
        **record,
        "asset_id": asset_id,
        "path": str(payload),
        "bytes": size,
        "credits": str(credits),
        "cache_bytes": cache_size(base),
        "cache_limit_bytes": MAX_CACHE_BYTES,
    }
    (target / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record
