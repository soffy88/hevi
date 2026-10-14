"""跨场/跨事件角色合并。

3O 归属(待上游): `oprim.character_fuse`。
青年/老年等同名不同特征应拆开——启发式看特征 Jaccard。
"""

from __future__ import annotations

import re

from hevi.layer4_legacy.script2video.oprim_impl.idea_parse import slugify

_AGE_MARKERS = ("童年", "少年", "青年", "中年", "老年", "child", "young", "old", "elderly")


def feature_tokens(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower()) if len(tok) > 1}


def should_split_identities(left_features: str, right_features: str) -> bool:
    """特征集合过散或年龄段冲突 → 拆成两个角色。"""
    left, right = feature_tokens(left_features), feature_tokens(right_features)
    if not left or not right:
        return False
    ages_l = {m for m in _AGE_MARKERS if m in left}
    ages_r = {m for m in _AGE_MARKERS if m in right}
    if ages_l and ages_r and ages_l.isdisjoint(ages_r):
        return True
    union = left | right
    return len(left & right) / len(union) < 0.15


def canonical_identifier(name: str) -> str:
    return slugify(name)


def merge_feature_text(existing: str, incoming: str) -> str:
    if not incoming:
        return existing
    if not existing:
        return incoming
    if incoming in existing:
        return existing
    return f"{existing}; {incoming}"


# Alias groups and CharacterCard synthesis for DRAMAKEY / ViMax
import json
from pathlib import Path
from typing import Any
from hevi.layer4_legacy.keyframe.oprim_impl.character_card import CharacterCard

_KNOWN_ALIAS_GROUPS = [
    {"primary": "王生", "aliases": ["王七", "书生", "王秀才", "弟子"], "gender": "male", "age_band": "young", "en": "young Chinese scholar in Hanfu robes, youthful face"},
    {"primary": "老道长", "aliases": ["道长", "老道", "师父", "道人", "法师"], "gender": "male", "age_band": "elderly", "en": "venerable elderly Taoist master with long white beard, grey robes"},
]


def are_aliases(name_a: str, name_b: str, *, custom_groups: list[dict[str, Any]] | None = None) -> bool:
    """Check if two names refer to the same character alias."""
    if name_a == name_b:
        return True
    groups = custom_groups or _KNOWN_ALIAS_GROUPS
    for g in groups:
        members = {g["primary"]} | set(g.get("aliases", []))
        if name_a in members and name_b in members:
            return True
    return False


def fuse_characters_to_cards(
    characters: list[Any],
    *,
    custom_alias_groups: list[dict[str, Any]] | None = None,
) -> list[CharacterCard]:
    """Fuse characters by name/aliases and generate consolidated CharacterCards."""
    groups = custom_alias_groups or _KNOWN_ALIAS_GROUPS
    fused: dict[str, CharacterCard] = {}

    for item in characters:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            desc = str(item.get("description") or "")
        else:
            name = str(getattr(item, "name", ""))
            desc = str(getattr(item, "description", ""))

        if not name:
            continue

        # Match to existing group
        matched_group = None
        for g in groups:
            members = {g["primary"]} | set(g.get("aliases", []))
            if name in members:
                matched_group = g
                break

        primary_name = matched_group["primary"] if matched_group else name
        primary_id = slugify(primary_name)

        if primary_id not in fused:
            gender = matched_group.get("gender", "male") if matched_group else ("female" if any(k in desc for k in ["女", "妇", "娘"]) else "male")
            age_band = matched_group.get("age_band", "young") if matched_group else ("elderly" if any(k in desc for k in ["老", "翁", "道长", "白须"]) else "young")
            en_tokens = matched_group.get("en", "") if matched_group else f"{age_band} Chinese {gender}"
            aliases = [a for a in (matched_group.get("aliases", []) if matched_group else []) if a != primary_name]
            if name != primary_name and name not in aliases:
                aliases.append(name)

            fused[primary_id] = CharacterCard(
                id=primary_id,
                name=primary_name,
                aliases=aliases,
                gender=gender,
                age_band=age_band,
                appearance_zh=desc,
                appearance_en_tokens=en_tokens,
                voice="zh_CN-huayan-medium.onnx",
                voice_speed=0.95 if age_band == "elderly" else 1.05,
            )
        else:
            card = fused[primary_id]
            if name != card.name and name not in card.aliases:
                card.aliases.append(name)
            card.appearance_zh = merge_feature_text(card.appearance_zh, desc)

    return list(fused.values())


def export_character_cards(cards: list[CharacterCard], output_path: Path | str) -> None:
    """Save character dossier cards to characters.json."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [c.to_dict() for c in cards]
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

