"""Character sheets that can be handed to the existing cast-card pipeline.

Every main character needs a bio, a relationship position, an arc and a real
defect, plus one to three visual markers.  The markers are written into the
same card fields ``hevi.ai_drama.series`` already locks for image consistency.
"""

from __future__ import annotations

from typing import Any

from .names import name_findings

MAIN_ROLES = {"主角", "反派", "重要配角", "lead", "villain", "deuteragonist"}
NON_DEFECTS = {"没有缺点", "太善良", "太完美", "心软", "善良", "正直", "无"}
MARKER_HINTS = (
    "疤", "痣", "眼镜", "耳钉", "项链", "戒指", "手表", "围巾", "帽子", "发卡", "纹身",
    "袖口", "领口", "鞋", "包", "手串", "助听器", "拐杖", "工牌", "手套", "创可贴",
    "录音笔", "钥匙", "笔记本", "水杯", "伞", "烫", "戒痕", "旧伤",
    "染", "短发", "长发", "马尾", "刘海", "胡子", "疤痕", "胎记",
)


def _finding(rule: str, severity: str, message: str, ref: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


def _relations_of(character: dict[str, Any]) -> list[dict[str, Any]]:
    raw = character.get("relations") or character.get("relationship") or []
    if isinstance(raw, str):
        return [{"target": raw, "type": ""}] if raw.strip() else []
    return [item for item in raw if isinstance(item, dict)]


def check_characters(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = list(name_findings(characters))
    names = {str(c.get("name") or "") for c in characters}
    ids = {str(c.get("id") or "") for c in characters}
    for index, character in enumerate(characters, start=1):
        cid = str(character.get("id") or f"c{index}")
        name = str(character.get("name") or "").strip()
        role = str(character.get("role") or "").strip()
        if not name:
            out.append(_finding("C-NAME", "must", f"角色 {cid} 缺名字", cid))
        if not role:
            out.append(_finding("C-ROLE", "must", f"角色「{name or cid}」缺关系定位/角色功能", cid))
        if role not in MAIN_ROLES:
            continue
        if not str(character.get("bio") or "").strip():
            out.append(_finding("C-BIO", "must", f"主角「{name}」缺小传", cid))
        relations = _relations_of(character)
        if not relations:
            out.append(_finding("C-REL", "must", f"主角「{name}」缺关系定位", cid))
        for relation in relations:
            target = str(relation.get("target") or "")
            if target and target not in names and target not in ids:
                out.append(_finding(
                    "C-REL-TARGET", "should",
                    f"「{name}」的关系对象「{target}」不在人物表", cid,
                ))
        arc = str(character.get("arc") or "").strip()
        if not arc:
            out.append(_finding("C-ARC", "must", f"主角「{name}」缺弧光", cid))
        elif not any(word in arc for word in ("从", "到", "最终", "转变", "变成", "学会")):
            out.append(_finding(
                "C-ARC", "should",
                f"「{name}」的弧光要写清从什么变成什么", cid,
            ))
        defect = str(character.get("defect") or "").strip()
        if not defect:
            out.append(_finding("C-DEFECT", "must", f"主角「{name}」没有缺陷", cid))
        elif defect in NON_DEFECTS or len(defect) < 3:
            out.append(_finding(
                "C-DEFECT", "must",
                f"「{name}」的缺陷「{defect}」不是缺陷；要写会害到自己的东西", cid,
            ))
        markers = [str(x) for x in character.get("visual_markers") or [] if str(x).strip()]
        if not markers:
            out.append(_finding("C-MARK", "must", f"主角「{name}」缺 1–3 个视觉标记", cid))
        elif len(markers) > 3:
            out.append(_finding("C-MARK", "should", f"「{name}」视觉标记超过 3 个，出图会漂", cid))
        for marker in markers:
            if not any(hint in marker for hint in MARKER_HINTS):
                out.append(_finding(
                    "C-MARK-FILM", "should",
                    f"「{name}」的视觉标记「{marker}」不好拍；写成看得见的物件/发型/伤", cid,
                ))
    return out


def build_cast_card(character: dict[str, Any], *, index: int, style: str = "live_action") -> dict[str, Any]:
    """Map a script character onto the fields the series cast card locks."""
    name = str(character.get("name") or f"角色{index}")
    markers = [str(x) for x in character.get("visual_markers") or [] if str(x).strip()]
    detail = "；".join(markers) or str(character.get("look") or "")
    outfit = character.get("outfit") or {}
    if not isinstance(outfit, dict):
        outfit = {}
    top = str(outfit.get("top") or character.get("top") or "深色外套")
    bottom = str(outfit.get("bottom") or character.get("bottom") or "长裤")
    shoes = str(outfit.get("shoes") or character.get("shoes") or "黑色布鞋")
    return {
        "id": str(character.get("id") or f"c{index}"),
        "name": name,
        "body": str(character.get("body") or "普通身材"),
        "hair": str(character.get("hair") or "黑色短发"),
        "hair_part": str(character.get("hair_part") or "自然分"),
        "eye_color": str(character.get("eye_color") or "深棕"),
        "signature_detail": detail,
        "outfit": {"top": top, "bottom": bottom, "shoes": shoes},
        "outfits": [{"top": top, "bottom": bottom, "shoes": shoes, "material": "棉", "color": "深色", "length": "常规"}],
        "personality": str(character.get("personality") or character.get("defect") or ""),
        "voice": character.get("voice") or {"description": "平静、偏低的普通话", "piper_voice": "zh_CN-huayan-medium.onnx"},
        "accessories": markers,
        "style": style,
    }


def build_characters(
    *,
    names: list[str],
    roles: list[str],
    relations: list[list[dict[str, Any]]] | None = None,
    bios: list[str] | None = None,
    defects: list[str] | None = None,
    arcs: list[str] | None = None,
    markers: list[list[str]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, name in enumerate(names, start=1):
        out.append({
            "id": f"c{index}",
            "name": name,
            "role": roles[index - 1] if index - 1 < len(roles) else "配角",
            "bio": (bios or [""] * len(names))[index - 1] if bios and index - 1 < len(bios) else "",
            "relations": (relations or [[]] * len(names))[index - 1]
            if relations and index - 1 < len(relations) else [],
            "defect": (defects or [""] * len(names))[index - 1]
            if defects and index - 1 < len(defects) else "",
            "arc": (arcs or [""] * len(names))[index - 1] if arcs and index - 1 < len(arcs) else "",
            "visual_markers": (markers or [[]] * len(names))[index - 1]
            if markers and index - 1 < len(markers) else [],
            "voice": {"description": "平静、偏低的普通话", "piper_voice": "zh_CN-huayan-medium.onnx"},
        })
    return out


__all__ = [
    "MAIN_ROLES",
    "build_cast_card",
    "build_characters",
    "check_characters",
]
