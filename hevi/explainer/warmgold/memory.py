"""制作记忆（按用户 / 按栏目）。

规则少、原话多：审片时用户说的纠正原话 + 日期，下次同栏目生成前注入。
条目修改需要用户确认；爆点库、零件清单、发布数据各只存一处。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("data/warmgold_memory")


def _root(root: str | Path | None) -> Path:
    return Path(root) if root else DEFAULT_ROOT


def _path(root: str | Path | None, user_id: str, column: str) -> Path:
    safe_user = "".join(ch for ch in user_id if ch.isalnum() or ch in "-_") or "anonymous"
    safe_col = "".join(ch for ch in column if ch.isalnum() or ch in "-_") or "default"
    return _root(root) / safe_user / f"{safe_col}.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": "hevi.warmgold.memory/1", "rules": [], "quotes": [], "diary": []}
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except json.JSONDecodeError:
        return {"schema": "hevi.warmgold.memory/1", "rules": [], "quotes": [], "diary": []}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_memory(
    user_id: str, column: str = "default", *, root: str | Path | None = None
) -> dict[str, Any]:
    return _load(_path(root, user_id, column))


def add_quote(
    user_id: str,
    column: str,
    quote: str,
    *,
    root: str | Path | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """记录一句审片原话。原话不改写、不总结。"""
    if not quote.strip():
        raise ValueError("empty quote")
    path = _path(root, user_id, column)
    data = _load(path)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "date": date or datetime.now(UTC).date().isoformat(),
        "quote": quote.strip(),
        "confirmed": True,
    }
    data.setdefault("quotes", []).append(entry)
    _save(path, data)
    return entry


def add_rule(
    user_id: str,
    column: str,
    rule: str,
    *,
    root: str | Path | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """规则必须用户确认后才写入；未确认只返回草稿。"""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "rule": rule.strip(),
        "confirmed": bool(confirmed),
        "date": datetime.now(UTC).date().isoformat(),
    }
    if not confirmed:
        return {**entry, "written": False}
    path = _path(root, user_id, column)
    data = _load(path)
    data.setdefault("rules", []).append(entry)
    _save(path, data)
    return {**entry, "written": True}


def update_entry(
    user_id: str,
    column: str,
    entry_id: str,
    *,
    text: str,
    root: str | Path | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    if not confirmed:
        raise PermissionError("条目修改需要用户确认")
    path = _path(root, user_id, column)
    data = _load(path)
    for bucket, key in (("rules", "rule"), ("quotes", "quote")):
        for item in data.get(bucket, []):
            if item.get("id") == entry_id:
                item[key] = text.strip()
                item["updated"] = datetime.now(UTC).isoformat()
                _save(path, data)
                result: dict[str, Any] = item
                return result
    raise KeyError(entry_id)


def write_diary(
    user_id: str,
    column: str,
    *,
    episode: str,
    did: str,
    changed: str = "",
    root: str | Path | None = None,
) -> dict[str, Any]:
    path = _path(root, user_id, column)
    data = _load(path)
    entry = {
        "date": datetime.now(UTC).isoformat(),
        "episode": episode,
        "did": did,
        "changed": changed,
    }
    data.setdefault("diary", []).append(entry)
    _save(path, data)
    return entry


def inject(user_id: str, column: str = "default", *, root: str | Path | None = None) -> str:
    """生成注入块：原话在前，规则在后；没有记忆返回空串。"""
    data = list_memory(user_id, column, root=root)
    quotes = [q for q in data.get("quotes", []) if q.get("confirmed")]
    rules = [r for r in data.get("rules", []) if r.get("confirmed")]
    if not quotes and not rules:
        return ""
    lines = ["【制作记忆 · 同栏目】"]
    lines.extend(f"- {q['date']} 用户原话：「{q['quote']}」" for q in quotes[-8:])
    lines.extend(f"- 已确认规则：{r['rule']}" for r in rules[-4:])
    return "\n".join(lines)
