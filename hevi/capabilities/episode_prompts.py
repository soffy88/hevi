"""Single-episode prompt compiler -- ``story.episode_prompts``.

Compiles one episode's shots into complete, generation-ready prompt texts.
Every shot resolves its characters and scene against the locked bible
(``bible``): character ids resolve to locked portrait blocks from
``visual_locks`` (falling back to a character entry's own ``block`` /
``portrait_block`` field), scene ids resolve to locked scene blocks.

Rules that matter:

* Unknown character/scene ids raise :class:`CapabilityError` -- a prompt
  must never be generated against a character or scene that does not exist.
* Missing fields are NEVER silently invented. The affected segment is
  literally marked ``[缺失]`` and the miss is recorded in
  ``compile_warnings`` for the pre-generation gates to judge as a blocker.
* The ``[动作]`` segment keeps the caller's action text verbatim: support
  points, direction, amplitude and stop positions are not rewritten.
  Every shot also carries ``blocks["action_nodes"]``: one action node per
  shot by contract. When the caller supplies ``action_nodes`` explicitly
  they are kept as-is (and a multi-node list is warned, for the gates to
  judge); otherwise exactly one node is derived from the action text
  (``source: "derived_from_action"``). The compiler never splits an
  action sentence into verbs on its own -- verb-level splitting is a
  separate, still-open rule, so a compound action sentence declared as
  one node is a declared primary node, not a verified single action.
* The ``[场景锁定]`` segment carries a spatial layout contract when one
  is available: ``spatial_layout`` (per-shot, falling back to the bible
  scene entry's ``layout``) with door / table / key props / light /
  character positions and facings. A missing layout, or a layout missing
  the static fields (door, table, light), is recorded in
  ``compile_warnings`` with field ``spatial_layout`` for the gates to
  block on; nothing is invented to fill it.
* A shot may carry ``costume_variant`` (``character_id``, ``outfit``,
  ``variant_id``): the compiler emits a variant record that splits the
  character lock block into an identity block and a style block (qisi
  identity/style separation, method only). The identity block locks the
  character's face anchors / hair / body proportions and never changes;
  a costume change swaps only the style block (outfit). The record
  reuses the asset-registry field names (``portrait_block`` / ``outfit``
  / ``signature_props`` / ``face_anchors``) so it can be registered
  without touching ``asset_library``; locked fields absent from the
  source are listed in ``missing_locked_fields``, never invented.
  Every shot's prompt is self-contained: a variant shot restates the
  full identity block and the new style block in its own text and never
  relies on a previous shot, an internal number or "same as above".
* Action-node mapping convention (self-defined; method sources are
  liyue one-shot-one-main-motion read-only, qisi one-shot-one-task and
  gnipbao phased action checking -- no code or example text copied):
  one main motion, including its enter / main / settle phases, is one
  node; two distinct tasks or motions are two nodes; each declared
  phase must actually appear in the action text (a settle phase that
  is not there is not invented). The concrete mapping table lives in
  the compiler tests (``ACTION_NODE_MAP``): 1 node keeps the shot,
  2 nodes is a major (split recommended), 3 or more is a blocker
  (must split). The compiler's derived single node is a fallback
  declaration of the primary node, not a verified single motion.
* The ``[否定约束]`` segment always starts from the four default negatives
  (no face swap, no unrelated people, no text artifact, no brand logo)
  and appends caller extras, deduplicated in order.

Output (``episode_prompts.json``) mirrors the script_polish report shape:
``episode_no``, ``title``, ``total_duration_sec``,
``total_dialogue_chars``, ``shots`` (each with ``shot_id``,
``prompt_text`` and machine-readable ``blocks``), ``must_know`` and
``compile_warnings``. ``must_know`` is passed through verbatim so the
drama gates can feed it to ``story.script_polish`` as its intent input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MISSING = "[缺失]"

DEFAULT_NEGATIVES = [
    "不换脸",
    "不加无关人物",
    "不出文字 artifact",
    "不出品牌 logo",
]

SEGMENT_ORDER = [
    "角色锁定",
    "场景锁定",
    "动作",
    "对白",
    "镜头",
    "风格",
    "时长",
    "否定约束",
    "首帧参照",
]

# Static layout fields: architecture and light do not move between shots
# of one scene, so the gates compare exactly these three. Key props and
# character positions move legitimately and are per-shot facts only.
SPATIAL_STATIC_FIELDS = ["door", "table", "light"]
SPATIAL_FIELD_LABELS = {
    "door": "门",
    "table": "桌",
    "key_props": "关键道具",
    "light": "光源",
    "character_positions": "人物站位",
}
# Locked identity fields for a costume variant: these never change, only
# the outfit does.
COSTUME_LOCKED_FIELDS = ["face_anchors", "hair", "body_proportions"]


def _normalize_spatial_layout(raw: Any) -> dict[str, Any] | None:
    """Normalize a spatial layout dict; None when no layout was given."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CapabilityError(
            "story.episode_prompts: 'spatial_layout' / scene 'layout' "
            "must be an object"
        )
    key_props_raw = raw.get("key_props")
    if key_props_raw is None:
        key_props: Any = None
    elif isinstance(key_props_raw, dict):
        key_props = { _as_str(k): _as_str(v) for k, v in key_props_raw.items() }
    elif isinstance(key_props_raw, list):
        key_props = [_as_str(v) for v in key_props_raw]
    else:
        key_props = _as_str(key_props_raw)
    positions_raw = raw.get("character_positions")
    if positions_raw is None:
        positions: Any = None
    elif isinstance(positions_raw, dict):
        positions = {}
        for who, pos in positions_raw.items():
            if isinstance(pos, dict):
                positions[_as_str(who)] = {
                    "position": _nonempty(pos.get("position")),
                    "facing": _nonempty(pos.get("facing")),
                }
            else:
                positions[_as_str(who)] = {
                    "position": _nonempty(pos),
                    "facing": None,
                }
    else:
        raise CapabilityError(
            "story.episode_prompts: 'character_positions' must be an object"
        )
    return {
        "door": _nonempty(raw.get("door")),
        "table": _nonempty(raw.get("table")),
        "key_props": key_props,
        "light": _nonempty(raw.get("light")),
        "character_positions": positions,
    }


def _merge_layouts(
    shot_layout: Any, scene_layout: Any
) -> dict[str, Any] | None:
    """Shot-level layout wins per field over the bible scene layout."""
    shot = _normalize_spatial_layout(shot_layout) if shot_layout is not None else None
    scene = _normalize_spatial_layout(scene_layout) if scene_layout is not None else None
    if shot is None:
        return scene
    if scene is None:
        return shot
    merged: dict[str, Any] = {}
    for key in ("door", "table", "key_props", "light", "character_positions"):
        merged[key] = shot[key] if shot[key] is not None else scene[key]
    return merged


def _layout_prompt_line(layout: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("door", "table", "key_props", "light", "character_positions"):
        value = layout.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            rendered = "；".join(
                f"{who}：{pos.get('position') or ''}"
                + (f"朝向{pos.get('facing')}" if pos.get("facing") else "")
                for who, pos in value.items()
                if isinstance(pos, dict)
            )
        elif isinstance(value, list):
            rendered = "、".join(value)
        else:
            rendered = value
        if rendered:
            parts.append(f"{SPATIAL_FIELD_LABELS[key]}：{rendered}")
    if not parts:
        return ""
    return "空间布局：" + "；".join(parts)


def _normalize_action_nodes(
    raw: Any, action: str | None, shot_id: str
) -> tuple[list[dict[str, Any]], str]:
    """Return (nodes, source). Explicit nodes are kept as-is; otherwise a
    single node is derived from the action text. Empty explicit list
    falls back to derivation; no action text at all yields no nodes."""
    if isinstance(raw, list) and raw:
        nodes: list[dict[str, Any]] = []
        for idx, item in enumerate(raw):
            if isinstance(item, dict):
                nodes.append(
                    {
                        "index": idx,
                        "text": _as_str(item.get("text", item.get("action", ""))),
                        "subject": _nonempty(item.get("subject")),
                    }
                )
            else:
                nodes.append(
                    {"index": idx, "text": _as_str(item), "subject": None}
                )
        return nodes, "explicit"
    if isinstance(raw, list) and not raw:
        pass  # empty explicit list: fall through to derivation
    elif raw is not None:
        raise CapabilityError(
            f"story.episode_prompts: 'action_nodes' must be a list (shot {shot_id})"
        )
    if action is None:
        return [], "derived_from_action"
    return [{"index": 0, "text": action, "subject": None}], "derived_from_action"


def _build_costume_variant(
    character_id: str,
    entry: dict[str, Any],
    visual_locks: dict[str, Any],
    variant: dict[str, Any],
    shot_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Build one asset-registry-compatible costume variant record.

    Locks face / hair / body proportions from the character entry or its
    visual lock, changes only the outfit. Returns (record, missing_fields):
    locked fields absent from the source are listed, never invented.
    """
    if not isinstance(variant, dict):
        raise CapabilityError(
            f"story.episode_prompts: 'costume_variant' must be an object "
            f"(shot {shot_id})"
        )
    outfit = _nonempty(variant.get("outfit"))
    variant_id = _nonempty(variant.get("variant_id")) or f"{character_id}_variant"
    lock = visual_locks.get(character_id)
    if not isinstance(lock, dict):
        lock = {}
    locked: dict[str, Any] = {}
    missing: list[str] = []
    for field in COSTUME_LOCKED_FIELDS:
        value = _nonempty(entry.get(field)) or _nonempty(lock.get(field))
        if value is None:
            missing.append(field)
        locked[field] = value
    base_block = _character_block(entry, character_id, visual_locks)
    portrait_block: str | None = None
    if base_block is not None and outfit is not None and not missing:
        portrait_block = base_block
        # Replace only the outfit mention when the base block carries one;
        # otherwise append the new outfit so the variant block is complete.
        old_outfit = _nonempty(entry.get("outfit")) or _nonempty(lock.get("outfit"))
        if old_outfit and old_outfit in portrait_block:
            portrait_block = portrait_block.replace(old_outfit, outfit)
        elif outfit not in portrait_block:
            portrait_block = f"{portrait_block}，{outfit}"
    # Identity block (locked half) vs style block (swapped half): the
    # identity block is composed only from locked fields actually present.
    present_locked = [locked[field] for field in COSTUME_LOCKED_FIELDS if locked[field]]
    identity_block = "、".join(present_locked) if present_locked else None
    style_block = outfit
    record = {
        "id": variant_id,
        "kind": "costume_variant",
        "character_id": character_id,
        "base_character_id": character_id,
        "name": _as_str(entry.get("name", character_id)),
        "face_anchors": locked["face_anchors"],
        "hair": locked["hair"],
        "body_proportions": locked["body_proportions"],
        "identity_block": identity_block,
        "style_block": style_block,
        "portrait_block": portrait_block,
        "outfit": outfit,
        "signature_props": _nonempty(entry.get("signature_props"))
        or _nonempty(lock.get("signature_props")),
        "locked": list(COSTUME_LOCKED_FIELDS),
        "changed": ["outfit"],
        "missing_locked_fields": missing,
    }
    return record, missing


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def _normalize_must_know(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "fact": _as_str(item.get("fact", "")),
                "keywords": [_as_str(k) for k in (item.get("keywords", []) or [])],
            }
        )
    return out


def _build_bible_maps(bible: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    characters: dict[str, Any] = {}
    for entry in bible.get("characters", []) or []:
        if isinstance(entry, dict) and entry.get("id") is not None:
            characters[_as_str(entry.get("id"))] = entry
    scenes: dict[str, Any] = {}
    for entry in bible.get("scenes", []) or []:
        if isinstance(entry, dict) and entry.get("id") is not None:
            scenes[_as_str(entry.get("id"))] = entry
    visual_locks: dict[str, Any] = {}
    raw_locks = bible.get("visual_locks", {}) or {}
    if isinstance(raw_locks, dict):
        for key, value in raw_locks.items():
            visual_locks[_as_str(key)] = value
    return characters, scenes, visual_locks


def _character_block(
    entry: dict[str, Any], char_id: str, visual_locks: dict[str, Any]
) -> str | None:
    for key in ("portrait_block", "block"):
        block = _nonempty(entry.get(key))
        if block is not None:
            return block
    return _nonempty(visual_locks.get(char_id))


def _compile_shot(
    raw: dict[str, Any],
    idx: int,
    characters: dict[str, Any],
    scenes: dict[str, Any],
    visual_locks: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> tuple[dict[str, Any], float, int]:
    shot_id = _nonempty(raw.get("shot_id")) or f"shot_{idx + 1:02d}"
    if raw.get("shot_id") is None:
        warnings.append(
            {
                "shot_id": shot_id,
                "field": "shot_id",
                "message": "shot_id 缺失，已用序号占位标识本镜（不补写任何提示词内容）。",
            }
        )

    # -- characters: unknown id is a hard error, missing lock is a warning.
    char_ids: list[str] = []
    for cid in raw.get("character_ids", []) or []:
        cid_str = _as_str(cid)
        if cid_str not in characters:
            raise CapabilityError(
                f"story.episode_prompts: unknown character id: {cid_str!r} "
                f"(shot {shot_id})"
            )
        char_ids.append(cid_str)
    char_entries: list[dict[str, Any]] = []
    char_lines: list[str] = []
    for cid in char_ids:
        entry = characters[cid]
        name = _as_str(entry.get("name", cid))
        block = _character_block(entry, cid, visual_locks)
        char_entries.append({"id": cid, "name": name, "block": block})
        if block is None:
            warnings.append(
                {
                    "shot_id": shot_id,
                    "field": "characters",
                    "message": f"角色 {name}（{cid}）缺失锁定肖像块。",
                }
            )
            char_lines.append(f"{name}（{cid}）：{MISSING}")
        else:
            char_lines.append(f"{name}（{cid}）：{block}")
    if not char_ids:
        warnings.append(
            {"shot_id": shot_id, "field": "characters", "message": "本镜未指定任何角色。"}
        )
    characters_segment = "\n".join(char_lines) if char_lines else MISSING

    # -- scene: unknown id is a hard error, missing block is a warning.
    scene_id = _nonempty(raw.get("scene_id"))
    scene_name: str | None = None
    scene_block: str | None = None
    if scene_id is None:
        warnings.append(
            {"shot_id": shot_id, "field": "scene", "message": "本镜未指定 scene_id。"}
        )
    else:
        if scene_id not in scenes:
            raise CapabilityError(
                f"story.episode_prompts: unknown scene id: {scene_id!r} "
                f"(shot {shot_id})"
            )
        entry = scenes[scene_id]
        scene_name = _as_str(entry.get("name", scene_id)) or scene_id
        scene_block = _nonempty(entry.get("block"))
        if scene_block is None:
            warnings.append(
                {
                    "shot_id": shot_id,
                    "field": "scene",
                    "message": f"场景 {scene_name}（{scene_id}）缺失锁定场景块。",
                }
            )
    scene_segment = scene_block if scene_block is not None else MISSING

    # -- spatial layout: shot-level wins per field over the bible scene layout.
    scene_entry = scenes.get(scene_id) if scene_id is not None else None
    scene_layout_raw = (
        scene_entry.get("layout") if isinstance(scene_entry, dict) else None
    )
    spatial_layout = _merge_layouts(raw.get("spatial_layout"), scene_layout_raw)
    if spatial_layout is None:
        warnings.append(
            {
                "shot_id": shot_id,
                "field": "spatial_layout",
                "message": (
                    "本镜缺空间布局：须给场景补门／桌／关键道具／光源的相对位置"
                    "与人物站位朝向（本镜 spatial_layout 或场景 layout）。"
                ),
            }
        )
    else:
        missing_static = [
            field for field in SPATIAL_STATIC_FIELDS if spatial_layout.get(field) is None
        ]
        if missing_static:
            labels = "、".join(SPATIAL_FIELD_LABELS[f] for f in missing_static)
            warnings.append(
                {
                    "shot_id": shot_id,
                    "field": "spatial_layout",
                    "message": f"本镜空间布局缺静态字段：{labels}。",
                }
            )
        layout_line = _layout_prompt_line(spatial_layout)
        if layout_line and scene_segment != MISSING:
            scene_segment = f"{scene_segment}\n{layout_line}"

    # -- action: verbatim, never rewritten.
    action = _nonempty(raw.get("action"))
    if action is None:
        warnings.append(
            {"shot_id": shot_id, "field": "action", "message": "本镜缺失动作描述。"}
        )
    action_segment = action if action is not None else MISSING

    # -- action nodes: one node per shot by contract.
    action_nodes, nodes_source = _normalize_action_nodes(
        raw.get("action_nodes"), action, shot_id
    )
    if len(action_nodes) > 1:
        warnings.append(
            {
                "shot_id": shot_id,
                "field": "action_nodes",
                "message": (
                    f"本镜含 {len(action_nodes)} 个动作节点，超过一镜一动作节点"
                    "的约定（门禁判 major，3 个及以上判 blocker）。"
                ),
            }
        )
    if action_nodes and action_segment != MISSING:
        node_lines = "\n".join(
            f"动作节点（{node['index'] + 1}）：{node['text']}"
            for node in action_nodes
        )
        action_segment = f"{action_segment}\n{node_lines}"

    # -- costume variants: same person, new outfit only; identity locked.
    costume_variants: list[dict[str, Any]] = []
    for variant_raw in raw.get("costume_variants", []) or []:
        if not isinstance(variant_raw, dict):
            raise CapabilityError(
                f"story.episode_prompts: 'costume_variants' entries must be "
                f"objects (shot {shot_id})"
            )
        variant_char = _as_str(variant_raw.get("character_id", ""))
        if variant_char not in characters:
            raise CapabilityError(
                f"story.episode_prompts: unknown character id in "
                f"costume_variant: {variant_char!r} (shot {shot_id})"
            )
        record, missing_locked = _build_costume_variant(
            variant_char, characters[variant_char], visual_locks, variant_raw, shot_id
        )
        if _nonempty(variant_raw.get("outfit")) is None:
            warnings.append(
                {
                    "shot_id": shot_id,
                    "field": "costume_variant",
                    "message": f"换装变体 {record['id']} 未指定新服装（outfit）。",
                }
            )
        if missing_locked:
            labels = "、".join(missing_locked)
            warnings.append(
                {
                    "shot_id": shot_id,
                    "field": "costume_variant",
                    "message": (
                        f"换装变体 {record['id']} 缺锁定字段未补写：{labels}；"
                        "变体记录已标 missing_locked_fields，注册前须补齐。"
                    ),
                }
            )
        costume_variants.append(record)
    if costume_variants and characters_segment != MISSING:
        # Self-contained restatement: every variant shot repeats the full
        # identity block and the new style block in its own text. Never
        # "same as above", never a reference to a previous shot.
        variant_lines = "\n".join(
            f"换装变体 {rec['id']}（{rec['name']}）：身份："
            f"{rec['identity_block'] or MISSING}；造型：{rec['outfit'] or MISSING}。"
            for rec in costume_variants
        )
        characters_segment = f"{characters_segment}\n{variant_lines}"

    # -- dialogue: absent key -> [缺失]; explicit empty list -> pure visual shot.
    dialogue_raw = raw.get("dialogue", None)
    dialogue: list[dict[str, Any]] | None
    if dialogue_raw is None:
        dialogue = None
        warnings.append(
            {"shot_id": shot_id, "field": "dialogue", "message": "本镜缺失对白字段。"}
        )
        dialogue_segment = MISSING
    elif not isinstance(dialogue_raw, list):
        raise CapabilityError(
            f"story.episode_prompts: 'dialogue' must be a list (shot {shot_id})"
        )
    elif len(dialogue_raw) == 0:
        dialogue = []
        dialogue_segment = "（纯视觉镜，无对白）"
    else:
        dialogue = []
        lines: list[str] = []
        for line in dialogue_raw:
            if not isinstance(line, dict):
                raise CapabilityError(
                    f"story.episode_prompts: dialogue line must be an object "
                    f"(shot {shot_id})"
                )
            speaker = _as_str(line.get("speaker", ""))
            text = _as_str(line.get("text", ""))
            language = _as_str(line.get("language", "")) or "中文"
            dialogue.append({"speaker": speaker, "text": text, "language": language})
            if not text.strip():
                warnings.append(
                    {
                        "shot_id": shot_id,
                        "field": "dialogue",
                        "message": f"说话人 {speaker} 的对白文本为空。",
                    }
                )
            lines.append(f"{speaker}（{language}）：{text}")
        dialogue_segment = "\n".join(lines)

    # -- camera / style / duration / first_frame: missing -> [缺失], no invention.
    camera = _nonempty(raw.get("camera"))
    if camera is None:
        warnings.append(
            {"shot_id": shot_id, "field": "camera", "message": "本镜缺失镜头描述。"}
        )
    style = _nonempty(raw.get("style"))
    if style is None:
        warnings.append(
            {"shot_id": shot_id, "field": "style", "message": "本镜缺失风格描述。"}
        )
    duration_raw = raw.get("duration_sec")
    duration_sec: float | None = None
    if isinstance(duration_raw, bool):
        duration_sec = None
    elif isinstance(duration_raw, (int, float)):
        duration_sec = float(duration_raw)
    elif isinstance(duration_raw, str) and duration_raw.strip():
        try:
            duration_sec = float(duration_raw.strip())
        except ValueError:
            duration_sec = None
    if duration_sec is None:
        warnings.append(
            {"shot_id": shot_id, "field": "duration", "message": "本镜缺失时长（duration_sec）。"}
        )
    duration_segment = f"{duration_sec:g} 秒" if duration_sec is not None else MISSING

    first_frame = _nonempty(raw.get("first_frame"))
    if first_frame is None:
        warnings.append(
            {"shot_id": shot_id, "field": "first_frame", "message": "本镜缺失首帧参照文本。"}
        )

    # -- negatives: defaults always present, extras appended, dedup in order.
    negatives: list[str] = []
    for item in DEFAULT_NEGATIVES:
        if item not in negatives:
            negatives.append(item)
    for item in raw.get("negatives", []) or []:
        text = _as_str(item).strip()
        if text and text not in negatives:
            negatives.append(text)
    negatives_segment = "\n".join(f"- {item}" for item in negatives)

    segments = {
        "角色锁定": characters_segment,
        "场景锁定": scene_segment,
        "动作": action_segment,
        "对白": dialogue_segment,
        "镜头": camera if camera is not None else MISSING,
        "风格": style if style is not None else MISSING,
        "时长": duration_segment,
        "否定约束": negatives_segment,
        "首帧参照": first_frame if first_frame is not None else MISSING,
    }
    prompt_text = "\n".join(
        f"[{name}]\n{segments[name]}" for name in SEGMENT_ORDER
    )

    blocks = {
        "character_ids": char_ids,
        "characters": char_entries,
        "character_names": [c["name"] for c in char_entries],
        "scene_id": scene_id,
        "scene_name": scene_name,
        "scene": scene_block,
        "spatial_layout": spatial_layout,
        "action": action,
        "action_nodes": action_nodes,
        "action_nodes_source": nodes_source,
        "costume_variants": costume_variants,
        "dialogue": dialogue,
        "camera": camera,
        "style": style,
        "duration_sec": duration_sec,
        "negatives": negatives,
        "first_frame": first_frame,
    }
    shot = {"shot_id": shot_id, "prompt_text": prompt_text, "blocks": blocks}
    dialogue_chars = sum(len(d["text"]) for d in (dialogue or []))
    return shot, (duration_sec or 0.0), dialogue_chars


def compile_episode_prompts(params: dict[str, Any]) -> dict[str, Any]:
    """Pure compile step (no file I/O): params -> prompt package payload."""
    bible = params.get("bible")
    if not isinstance(bible, dict):
        raise CapabilityError("story.episode_prompts: 'bible' must be an object")
    episode = params.get("episode")
    if not isinstance(episode, dict):
        raise CapabilityError("story.episode_prompts: 'episode' must be an object")
    shots_raw = episode.get("shots", []) or []
    if not isinstance(shots_raw, list):
        raise CapabilityError("story.episode_prompts: 'episode.shots' must be a list")
    must_know = _normalize_must_know(
        params.get("must_know", episode.get("must_know", []))
    )
    characters, scenes, visual_locks = _build_bible_maps(bible)

    warnings: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    total_duration = 0.0
    total_dialogue_chars = 0
    all_costume_variants: list[dict[str, Any]] = []
    for idx, raw in enumerate(shots_raw):
        if not isinstance(raw, dict):
            raise CapabilityError(
                f"story.episode_prompts: shot {idx} must be an object"
            )
        shot, dur, chars = _compile_shot(
            raw, idx, characters, scenes, visual_locks, warnings
        )
        shots.append(shot)
        all_costume_variants.extend(shot["blocks"].get("costume_variants", []) or [])
        total_duration += dur
        total_dialogue_chars += chars

    return {
        "episode_no": episode.get("episode_no"),
        "title": episode.get("title", ""),
        "total_duration_sec": total_duration,
        "total_dialogue_chars": total_dialogue_chars,
        "shots": shots,
        "must_know": must_know,
        "compile_warnings": warnings,
        "costume_variants": all_costume_variants,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bible": {"type": "object"},
        "episode": {"type": "object"},
        "must_know": {"type": "array"},
    },
    "required": ["bible", "episode"],
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "episode_prompts.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    payload = compile_episode_prompts(params)
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_episode_prompts_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.episode_prompts",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "单集 prompt 编译器：把 bible 锁定角色块/场景块解析进每一镜，"
                "逐镜输出含角色锁定、场景锁定、动作（原样保留）、对白、镜头、"
                "风格、时长、否定约束（含四条默认否定）、首帧参照共 9 段的完整"
                " prompt。未知角色/场景 id 抛错；缺失字段标 [缺失] 并记入"
                " compile_warnings，绝不静默补写。must_know 原样透传，供"
                " story.drama_gates 转交 story.script_polish 作意图输入。"
                "每镜另带动作节点（blocks.action_nodes，一镜一节点约定；"
                "显式多节点记警告）、空间布局（blocks.spatial_layout，"
                "本镜优先、场景 layout 兜底，缺失记警告）与换装变体"
                "（blocks.costume_variants：锁定块拆为身份块与造型块，"
                "换装只换造型块，每镜提示词自足重述身份块与新造型，"
                "不依赖上一镜或“同上”；与资产注册表同字段名，"
                "缺锁定字段只标 missing 不补写）。"
            ),
            line="episode_prompts",
        )
    )
    return ["story.episode_prompts"]


register_episode_prompts_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.episode_prompts on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
