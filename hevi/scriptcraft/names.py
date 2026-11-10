"""Name hygiene for short drama / short film characters.

The brief asks for a blacklist of names hevi's own dramas keep reusing and for
main characters to avoid them, with distinct surnames.  The list is data, not
an opinion, so it lives in ``data/name_blacklist.json`` and can be audited.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data" / "name_blacklist.json"

SURNAME_POOL = (
    "周", "程", "方", "秦", "江", "贺", "严", "岑", "邵", "路", "柏", "简",
    "祝", "樊", "商", "郁", "成", "阮", "宁", "裴", "蒋", "黎", "卫", "庄",
    "章", "段", "闻", "席", "边", "时",
)
GIVEN_POOL = (
    "青禾", "知远", "见川", "素问", "明礼", "亦宁", "云开", "南乔", "望山",
    "长风", "清和", "立夏", "秋白", "若水", "子衿", "一鸣", "承宇", "星澜",
    "书言", "砚秋", "竹青", "鹿鸣", "予安", "序白", "遥川", "听澜", "归舟",
    "既白", "含章", "照野", "观棋", "闻笛", "枕石", "行舟", "怀瑾", "映川",
)

MAIN_ROLES = {"主角", "反派", "重要配角", "lead", "villain", "deuteragonist"}


@lru_cache(maxsize=1)
def load_blacklist() -> dict[str, list[str]]:
    try:
        data = json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"names": [], "chars": [], "surnames": []}
    return {
        "names": [str(x) for x in data.get("names") or []],
        "chars": [str(x) for x in data.get("chars") or []],
        "surnames": [str(x) for x in data.get("surnames") or []],
    }


def blacklist_names() -> frozenset[str]:
    return frozenset(load_blacklist()["names"])


def blacklist_chars() -> frozenset[str]:
    return frozenset(load_blacklist()["chars"])


def blacklist_surnames() -> frozenset[str]:
    return frozenset(load_blacklist()["surnames"])


def is_main(character: dict[str, Any]) -> bool:
    return str(character.get("role") or "").strip() in MAIN_ROLES


def name_findings(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = blacklist_names()
    chars = blacklist_chars()
    surnames = blacklist_surnames()
    out: list[dict[str, Any]] = []
    seen_surnames: dict[str, str] = {}
    for index, character in enumerate(characters, start=1):
        name = str(character.get("name") or "").strip()
        cid = str(character.get("id") or index)
        if not name:
            out.append(_finding("N-NAME", "must", f"角色 {cid} 没有名字", cid))
            continue
        if not is_main(character):
            continue
        if name in names:
            out.append(_finding(
                "N-BLACKLIST", "must",
                f"主角名「{name}」在 hevi 高频姓名黑名单里", cid,
            ))
        hits = [ch for ch in chars if ch in name]
        if hits:
            out.append(_finding(
                "N-BLACKCHAR", "should",
                f"主角名「{name}」用了高频字 {'/'.join(hits)}", cid,
            ))
        surname = name[0]
        if surname in surnames:
            out.append(_finding(
                "N-SURNAME", "must",
                f"主角姓氏「{surname}」在 hevi 高频姓氏表里", cid,
            ))
        if surname in seen_surnames:
            out.append(_finding(
                "N-SURNAME-DUP", "must",
                f"主角「{name}」与「{seen_surnames[surname]}」同姓，短剧里容易混", cid,
            ))
        else:
            seen_surnames[surname] = name
    return out


def pick_names(topic: str, count: int = 4) -> list[str]:
    """Deterministic, blacklist-safe names with distinct surnames."""
    digest = hashlib.sha256(str(topic or "untitled").encode("utf-8")).hexdigest()
    names = blacklist_names()
    chars = blacklist_chars()
    banned_surnames = blacklist_surnames()
    surnames = [s for s in SURNAME_POOL if s not in banned_surnames]
    givens = [g for g in GIVEN_POOL if not any(ch in g for ch in chars)]
    out: list[str] = []
    used_surnames: set[str] = set()
    used_givens: set[str] = set()
    cursor = int(digest[:8], 16)
    guard = 0
    while len(out) < count and guard < 400:
        guard += 1
        surname = surnames[(cursor + guard * 7) % len(surnames)]
        given = givens[(cursor // 3 + guard * 5) % len(givens)]
        candidate = surname + given
        if surname in used_surnames or given in used_givens or candidate in names:
            continue
        used_surnames.add(surname)
        used_givens.add(given)
        out.append(candidate)
    while len(out) < count:
        out.append(f"角色{len(out) + 1}")
    return out


def _finding(rule: str, severity: str, message: str, ref: str) -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


__all__ = [
    "GIVEN_POOL",
    "MAIN_ROLES",
    "SURNAME_POOL",
    "blacklist_chars",
    "blacklist_names",
    "blacklist_surnames",
    "is_main",
    "load_blacklist",
    "name_findings",
    "pick_names",
]
