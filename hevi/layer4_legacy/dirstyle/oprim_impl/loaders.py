"""Style library loaders — used by oprim."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.dirstyle.oprim_impl.models import (
    ARTICLE_DIRECTOR_IDS,
    DIRSTYLE_DATA_DIR,
    SCHEMA_PATH,
    DirectorStyle,
    from_dict,
)


def _validate(data: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        from jsonschema import validate as _validate_jsonschema
    except ImportError:
        return
    _validate_jsonschema(instance=data, schema=schema)


def load_styles(data_dir: Path | None = None) -> dict[str, DirectorStyle]:
    """Load all style JSON files from *data_dir*, returning id -> DirectorStyle.

    Schema validation is applied per-file; a failed validation raises ValueError
    with the first error message so callers see a loud failure instead of a
    silent empty dict.
    """
    src = Path(data_dir) if data_dir else DIRSTYLE_DATA_DIR
    schema: dict[str, Any] = {}
    schema_path = SCHEMA_PATH if data_dir is None else (src / "schema.json")
    if schema_path.exists():
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)

    out: dict[str, DirectorStyle] = {}
    for p in sorted(src.glob("*.json")):
        if p.name == "schema.json":
            continue
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if schema:
            try:
                _validate(raw, schema)
            except Exception as e:
                raise ValueError(f"style {p.name} failed schema: {e}") from e
        out[raw["id"]] = from_dict(raw)
    return out


def get_style(style_id: str, styles: dict[str, DirectorStyle] | None = None) -> DirectorStyle:
    """Resolve one style by id. Raises ValueError on miss."""
    pool = styles if styles is not None else load_styles()
    if style_id not in pool:
        raise ValueError(
            f"Unknown director style {style_id!r}. "
            f"Known: {', '.join(sorted(pool))}"
        )
    return pool[style_id]


def list_styles(styles: dict[str, DirectorStyle] | None = None) -> list[str]:
    pool = styles if styles is not None else load_styles()
    return sorted(pool.keys())


def check_article_directors(styles: dict[str, DirectorStyle] | None = None) -> set[str]:
    pool = styles if styles is not None else load_styles()
    return set(ARTICLE_DIRECTOR_IDS) & set(pool.keys())
