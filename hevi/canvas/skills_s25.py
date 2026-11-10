"""S25：文字技能库（带版本、启用/停用、版本回退）。

技能是**方法**，不是新的生成管线：``SKILL.md`` 给画布助手/外部调用方读，
执行仍走既有节点与工具。每个技能：

* 固定 ``version`` 与内容 ``sha256``（改内容必须发新版本，避免“悄悄变了”）；
* ``versions/`` 保留历史文件，可读、可回退；
* 启用状态存在 ``output/canvas_s25/skills_state.json``，只影响“列不列给助手”，
  不删除文件。

本轮只收录自写的 3 个纯文字技能（双镜头分镜 / 采访提纲 / 素材清单与授权）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LIBRARY_ROOT = Path(__file__).resolve().parents[1] / "skills" / "library_s25"

BUILTIN_IDS = ("two-shot-storyboard", "interview-outline", "rights-log")


def state_path() -> Path:
    return Path(os.environ.get("HEVI_CANVAS_SKILLS_STATE", "output/canvas_s25/skills_state.json"))


def _read_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {"disabled": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"disabled": []}
    if not isinstance(data, dict):
        return {"disabled": []}
    data.setdefault("disabled", [])
    return data


def _write_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _meta(skill_id: str) -> dict[str, Any]:
    path = LIBRARY_ROOT / skill_id / "skill.json"
    if not path.is_file():
        raise ValueError(f"技能不存在：{skill_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_skills(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    state = _read_state()
    disabled = set(state.get("disabled") or [])
    items: list[dict[str, Any]] = []
    for folder in sorted(LIBRARY_ROOT.iterdir()) if LIBRARY_ROOT.is_dir() else []:
        if not (folder / "skill.json").is_file():
            continue
        try:
            meta = _meta(folder.name)
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        enabled = folder.name not in disabled
        if not include_disabled and not enabled:
            continue
        items.append(
            {
                "id": meta.get("id") or folder.name,
                "title": meta.get("title") or folder.name,
                "summary": meta.get("summary") or "",
                "tags": meta.get("tags") or [],
                "version": meta.get("version") or 1,
                "sha256": meta.get("sha256") or "",
                "versions": [v.get("version") for v in meta.get("versions") or []],
                "enabled": enabled,
            }
        )
    return items


def get_skill(skill_id: str, *, version: int | None = None) -> dict[str, Any]:
    meta = _meta(skill_id)
    folder = LIBRARY_ROOT / skill_id
    rel = "SKILL.md"
    chosen = int(version or meta.get("version") or 1)
    if version is not None:
        match = next(
            (v for v in meta.get("versions") or [] if int(v.get("version") or 0) == chosen), None
        )
        if not match:
            raise ValueError(f"技能版本不存在：{skill_id} v{chosen}")
        rel = str(match.get("file") or rel)
    path = folder / rel
    if not path.is_file():
        raise ValueError(f"技能文件缺失：{skill_id} {rel}")
    content = path.read_text(encoding="utf-8")
    return {
        "id": meta.get("id") or skill_id,
        "title": meta.get("title") or skill_id,
        "summary": meta.get("summary") or "",
        "tags": meta.get("tags") or [],
        "version": chosen,
        "content": content,
        "sha256": _sha(content),
        "versions": meta.get("versions") or [],
        "enabled": skill_id not in set(_read_state().get("disabled") or []),
    }


def set_enabled(skill_id: str, enabled: bool) -> dict[str, Any]:
    meta = _meta(skill_id)
    state = _read_state()
    disabled = set(state.get("disabled") or [])
    if enabled:
        disabled.discard(skill_id)
    else:
        disabled.add(skill_id)
    state["disabled"] = sorted(disabled)
    _write_state(state)
    return {"id": skill_id, "title": meta.get("title"), "enabled": enabled}


def skill_manifest() -> dict[str, Any]:
    """给画布助手/外部 Agent 的窄清单（只列已启用，含版本与哈希）。"""
    return {
        "skills": [
            {k: item[k] for k in ("id", "title", "summary", "version", "sha256", "tags")}
            for item in list_skills(include_disabled=False)
        ],
        "root": str(LIBRARY_ROOT),
    }
