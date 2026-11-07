"""Shared path resolution for knowledge skills."""

from __future__ import annotations

from pathlib import Path

from oprim._config import cfg


def stratum_home() -> Path:
    return Path(cfg.get("STRATUM_HOME", str(Path.home() / ".stratum")))


def meta_db_path() -> Path:
    return stratum_home() / "meta.duckdb"


def tantivy_path() -> Path:
    return stratum_home() / "index" / "tantivy"


def lancedb_path() -> Path:
    return stratum_home() / "index" / "lance"


def substrate_data_path() -> Path:
    return stratum_home() / "data" / "substrate"
