"""Motion Prompt 离线词条库（只读，不联网）。

数据：hevi/avcraft/data/motion_prompt/catalog.json —— vendored 自 showheyohtaki/motion-prompt api/v1
（MIT License (c) 2026 Shohei Ohtaki，见同目录 LICENSE/NOTICE.md）；zh_alias.json 为 hevi 自编中文别名。
也可指向上游完整克隆的 api/v1 目录（base=...）；若有 e/{id}.txt 可用 motion_element_code 读取（含首行版权注释，原样返回）。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "motion_prompt"
CREDIT = "Motion Prompt · MIT License (c) 2026 Shohei Ohtaki · https://showheyohtaki.github.io/motion-prompt/"


def _resolve(base: str | Path | None) -> Path:
    b = Path(base or os.environ.get("HEVI_MOTION_PROMPT_DIR") or DATA_DIR)
    if (b / "api" / "v1" / "catalog.json").exists():
        b = b / "api" / "v1"
    if not (b / "catalog.json").exists():
        raise FileNotFoundError(f"motion catalog not found under {b}")
    return b


@lru_cache(maxsize=4)
def _load(base: str) -> dict:
    b = Path(base)
    raw = json.loads((b / "catalog.json").read_text(encoding="utf-8"))
    alias_p = b / "zh_alias.json" if (b / "zh_alias.json").exists() else DATA_DIR / "zh_alias.json"
    zh = json.loads(alias_p.read_text(encoding="utf-8")) if alias_p.exists() else {}
    els = []
    for e in raw["elements"]:
        e = dict(e)
        e["zh"] = list(zh.get(e["slug"], []))
        e["credit"] = f"Motion Prompt #{e['id']} · MIT License (c) 2026 Shohei Ohtaki"
        els.append(e)
    return {
        "version": raw.get("version"),
        "source": raw.get("repo"),
        "base": str(b),
        "packs": {p["pack"]: p for p in raw.get("packs", [])},
        "elements": els,
        "by_id": {e["id"]: e for e in els},
        "by_slug": {e["slug"]: e for e in els},
        "credit": CREDIT,
    }


def motion_catalog_load(base: str | Path | None = None) -> dict:
    """返回 {version, packs{pack:meta}, elements[...], by_id, by_slug, credit}；每个元素附 zh 别名与 credit。缓存。"""
    return _load(str(_resolve(base)))


def motion_get(catalog: dict, key: str) -> dict | None:
    """按 id（'027'/'27'/'#027'）、slug 或中文/日文/英文名取元素。"""
    k = str(key).strip().lstrip("#")
    if k.isdigit():
        return catalog["by_id"].get(k.zfill(3))
    if k in catalog["by_slug"]:
        return catalog["by_slug"][k]
    kl = k.lower()
    for e in catalog["elements"]:
        if kl in (e["name"]["en"].lower(), e["name"]["ja"]) or k in e["zh"]:
            return e
    return None


def motion_element_code(catalog: dict, key: str, lang: str = "en") -> str | None:
    """若 base 下有上游 {lang}/e/{id}.txt（spec+Canvas 代码），原样返回（保留首行版权注释）；vendored 精简数据里没有则 None。"""
    e = motion_get(catalog, key)
    if not e:
        return None
    p = Path(catalog["base"]) / lang / "e" / f"{e['id']}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None
