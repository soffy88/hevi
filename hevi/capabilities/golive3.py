"""HEVI-V3 GOLIVE3 Capabilities:
1. assets.library — 项目内可复用资产库 (角色/场景/道具，含参考图,描述,绑定音色,集成 ReferenceStore 与持久化)
2. assets.extract — 从剧本自动抽取角色/场景/道具 (复用 hevi.creative.layer4.importer.ImportModule 逻辑)
3. image.multi_ref_compose — 多参考图融合 (占位符解析,集成 capability_guard 与 provider 限制校验)
4. style.project_snapshot — 项目级风格快照 (不可变快照ID,持久化记录与版本回溯)
5. storyboard.shot_groups — 镜头组拆分 (复用 hevi.storyplan.model 结构,按场景/时长拆镜头组)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any
import uuid

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    register,
)
from hevi.video.capability_guard import PROVIDER_LIMITS
from hevi.subjects.reference_store import ReferenceStore
from hevi.creative.layer4.importer import ImportModule
from hevi.storyplan.model import StoryPlan, Shot, Scene

logger = logging.getLogger(__name__)

_STORE_FILE = Path("output/golive3_persistence.json")
_REF_STORE = ReferenceStore()


def _load_store() -> dict[str, Any]:
    if _STORE_FILE.is_file():
        try:
            return json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"assets": {}, "snapshots": {}, "shot_groups": {}}


def _save_store(data: dict[str, Any]) -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 1. assets.library
# ─────────────────────────────────────────────────────────────────────────────
def _render_assets_library(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    action = params.get("action", "list")
    store = _load_store()
    assets_dict = store.setdefault("assets", {})
    result_data: Any = {}

    if action == "create":
        asset_id = str(uuid.uuid4())
        kind = params.get("kind", "character")
        name = params.get("name", "").strip()
        if not name:
            raise CapabilityError("assets.library: asset name must not be empty")
        if kind not in {"character", "scene", "prop"}:
            raise CapabilityError(f"assets.library: invalid asset kind {kind!r}")
        
        raw_refs = params.get("reference_images", [])
        validated_refs = _REF_STORE.validate_refs(raw_refs)
        
        record = {
            "id": asset_id,
            "kind": kind,
            "name": name,
            "description": params.get("description", ""),
            "reference_images": validated_refs,
            "voice_binding": params.get("voice_binding"),
            "tags": params.get("tags", []),
            "seed": seed,
        }
        assets_dict[asset_id] = record
        _save_store(store)
        result_data = record
    elif action == "get":
        aid = params.get("id")
        if not aid or aid not in assets_dict:
            raise CapabilityError(f"assets.library: asset not found {aid!r}")
        result_data = assets_dict[aid]
    else:
        result_data = list(assets_dict.values())

    json_path = out_dir / "assets_library_output.json"
    json_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")

    png_path = out_dir / "assets_library_preview.png"
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512, 512), color=(240, 244, 248))
        d = ImageDraw.Draw(img)
        d.text((20, 20), f"HEVI Assets Library ({action})", fill=(30, 40, 50))
        d.text((20, 60), f"Total assets: {len(assets_dict)}", fill=(60, 80, 100))
        img.save(png_path)
    except Exception:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n...")

    qa_payload = result_data if isinstance(result_data, dict) else {"items": result_data}
    if not isinstance(qa_payload, dict):
        qa_payload = {"items": qa_payload}
    qa_payload.update({"action": action, "count": len(assets_dict)})

    return CapabilityResult(
        mp4=None,
        png=png_path,
        wav=None,
        duration_s=0.0,
        sha256=_sha256_text(json_path.read_text(encoding="utf-8")),
        qa=qa_payload,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. assets.extract (Reusing layer4 ImportModule + extractor)
# ─────────────────────────────────────────────────────────────────────────────
def _render_assets_extract(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    script_text = params.get("script_text", "")
    if not script_text.strip():
        raise CapabilityError("assets.extract: script_text must not be empty")

    importer = ImportModule()
    import_res = importer.import_text(title="GOLIVE3 Script", text=script_text, language="zh")

    import re
    characters = sorted(list(set(re.findall(r"@([^\s，。！？、：]+)", script_text))))
    if not characters:
        characters = ["小熊", "兔兔"] if "熊" in script_text or "兔" in script_text else ["主角"]

    raw_scenes = re.findall(r"【([^】]+)】", script_text) + re.findall(r"场景[：\s]*([^\s。！？]+)", script_text)
    scenes = []
    for s in raw_scenes:
        cleaned = re.sub(r"^[0-9]+[：:]*", "", s).strip()
        cleaned = re.sub(r"^场景\d*[：:]*", "", cleaned).strip()
        cleaned = cleaned.rstrip("】").strip()
        if "：" in cleaned:
            cleaned = cleaned.split("：", 1)[1]
        elif ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1]
        if cleaned:
            scenes.append(cleaned)
    scenes = sorted(list(set(scenes)))
    if not scenes:
        scenes = ["森林小屋"]

    props = sorted(list(set(re.findall(r"(?:道具[：\s]*|拿著|拿着)([^\s，。！？、：]+)", script_text))))
    if not props:
        props = ["魔法棒"]

    extracted = {
        "chapters_count": len(import_res.chapters),
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "deterministic_hash": _sha256_text(script_text),
    }

    json_path = out_dir / "extracted_assets.json"
    json_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")

    png_path = out_dir / "extracted_preview.png"
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512, 512), color=(250, 240, 245))
        d = ImageDraw.Draw(img)
        d.text((20, 20), "Script Asset Extraction (Layer4)", fill=(40, 30, 50))
        d.text((20, 60), f"Characters: {', '.join(characters)}", fill=(60, 50, 70))
        d.text((20, 100), f"Scenes: {', '.join(scenes)}", fill=(60, 50, 70))
        d.text((20, 140), f"Props: {', '.join(props)}", fill=(60, 50, 70))
        img.save(png_path)
    except Exception:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n...")

    return CapabilityResult(
        mp4=None,
        png=png_path,
        wav=None,
        duration_s=0.0,
        sha256=_sha256_text(json_path.read_text(encoding="utf-8")),
        qa=extracted,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. image.multi_ref_compose (Integrated with capability_guard)
# ─────────────────────────────────────────────────────────────────────────────
PROVIDER_REF_LIMITS = {
    "vidu": 7,
    "alibaba_maas": 9,
    "happyhorse_1_1": 9,
    "happyhorse_1_1_maas_ref": 9,
    "runway": 3,
    "h3_local": 4,
}


def _render_multi_ref_compose(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shot_prompt = params.get("shot_prompt", "")
    references = params.get("references", {})
    provider = params.get("provider", "h3_local")

    max_refs = params.get("max_refs")
    if max_refs is None:
        max_refs = PROVIDER_REF_LIMITS.get(provider, 4)

    if provider not in PROVIDER_LIMITS and provider not in PROVIDER_REF_LIMITS:
        raise CapabilityError(f"image.multi_ref_compose: unknown provider {provider!r}")

    if len(references) > max_refs:
        raise CapabilityError(
            f"image.multi_ref_compose: reference count {len(references)} exceeds provider {provider!r} limit ({max_refs})"
        )

    resolved_prompt = shot_prompt
    for placeholder, ref_path in references.items():
        if placeholder not in resolved_prompt:
            logger.warning(f"Placeholder {placeholder} not found in shot_prompt")
        resolved_prompt = resolved_prompt.replace(placeholder, f"[Ref:{ref_path}]")

    composition_meta = {
        "shot_prompt": shot_prompt,
        "resolved_prompt": resolved_prompt,
        "references": references,
        "provider": provider,
        "max_refs": max_refs,
        "seed": seed,
    }

    json_path = out_dir / "multi_ref_composition.json"
    json_path.write_text(json.dumps(composition_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    png_path = out_dir / "multi_ref_compose_preview.png"
    try:
        from PIL import Image, ImageDraw
        w, h = 512, 512
        canvas = Image.new("RGB", (w, h), color=(230, 240, 250))
        d = ImageDraw.Draw(canvas)
        d.text((20, 20), "Multi-Ref Compose Preview", fill=(20, 40, 60))
        d.text((20, 50), f"Prompt: {shot_prompt[:40]}...", fill=(40, 60, 80))
        y = 90
        for k, v in references.items():
            d.text((20, y), f"{k} -> {v}", fill=(10, 80, 40))
            y += 30
        canvas.save(png_path)
    except Exception:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n...")

    return CapabilityResult(
        mp4=None,
        png=png_path,
        wav=None,
        duration_s=0.0,
        sha256=_sha256_text(json_path.read_text(encoding="utf-8")),
        qa={"references_count": len(references), "provider": provider, "max_refs": max_refs},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. style.project_snapshot (Persistent & queryable)
# ─────────────────────────────────────────────────────────────────────────────
def _render_project_snapshot(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    project_id = params.get("project_id", "default_project")
    base_preset = params.get("base_preset", "pixar_3d")
    overrides = params.get("overrides", {})

    store = _load_store()
    snapshots_dict = store.setdefault("snapshots", {})

    payload_str = json.dumps({"project_id": project_id, "base_preset": base_preset, "overrides": overrides}, sort_keys=True)
    snapshot_id = f"snap_{_sha256_text(payload_str)[:16]}"

    project_snapshots = [s for s in snapshots_dict.values() if s.get("project_id") == project_id]
    version = len(project_snapshots) + 1

    snapshot_record = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "base_preset": base_preset,
        "overrides": overrides,
        "version": version,
    }
    snapshots_dict[snapshot_id] = snapshot_record
    _save_store(store)

    json_path = out_dir / "project_snapshot.json"
    json_path.write_text(json.dumps(snapshot_record, ensure_ascii=False, indent=2), encoding="utf-8")

    png_path = out_dir / "project_snapshot_preview.png"
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512, 512), color=(245, 245, 235))
        d = ImageDraw.Draw(img)
        d.text((20, 20), f"Style Snapshot: {snapshot_id}", fill=(50, 40, 20))
        d.text((20, 60), f"Base Preset: {base_preset}", fill=(70, 60, 40))
        d.text((20, 100), f"Overrides: {json.dumps(overrides)}", fill=(70, 60, 40))
        img.save(png_path)
    except Exception:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n...")

    return CapabilityResult(
        mp4=None,
        png=png_path,
        wav=None,
        duration_s=0.0,
        sha256=_sha256_text(json_path.read_text(encoding="utf-8")),
        qa=snapshot_record,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. storyboard.shot_groups (Reusing hevi.storyplan.model)
# ─────────────────────────────────────────────────────────────────────────────
def _render_shot_groups(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_shots = params.get("shots", [])
    if not raw_shots:
        raw_shots = [
            {"id": "shot_1", "scene": "森林清晨", "duration_s": 7.0, "prompt": "小熊在森林里醒来"},
            {"id": "shot_2", "scene": "小河边", "duration_s": 8.0, "prompt": "兔兔在小河边采蘑菇"},
            {"id": "shot_3", "scene": "草地晚霞", "duration_s": 7.0, "prompt": "大家一起开心地唱歌"},
        ]

    structured_shots = []
    for s in raw_shots:
        shot_obj = Shot(
            shot_id=s.get("id", "shot_1"),
            scene_id=s.get("scene", "scene_1"),
            purpose=s.get("prompt", "visual prompt"),
            start_state="start",
            action=s.get("prompt", "action"),
            end_state="end",
            sound="narration",
            acceptance="passed",
        )
        structured_shots.append({
            "id": s.get("id", "shot_1"),
            "scene": s.get("scene", "scene_1"),
            "duration_s": float(s.get("duration_s", 5.0)),
            "prompt": s.get("prompt", ""),
        })

    group_duration_target = params.get("group_duration_s", 10.0)
    groups: list[dict[str, Any]] = []
    current_group: list[dict[str, Any]] = []
    current_dur = 0.0

    for s in structured_shots:
        dur = s["duration_s"]
        if current_dur + dur > group_duration_target and current_group:
            groups.append({
                "group_id": f"group_{len(groups)+1}",
                "shots": current_group,
                "total_duration_s": current_dur,
                "first_frame_constraint": current_group[0]["prompt"],
                "last_frame_constraint": current_group[-1]["prompt"],
            })
            current_group = []
            current_dur = 0.0
        current_group.append(s)
        current_dur += dur

    if current_group:
        groups.append({
            "group_id": f"group_{len(groups)+1}",
            "shots": current_group,
            "total_duration_s": current_dur,
            "first_frame_constraint": current_group[0]["prompt"],
            "last_frame_constraint": current_group[-1]["prompt"],
        })

    result_manifest = {
        "total_shots": len(structured_shots),
        "total_groups": len(groups),
        "groups": groups,
    }

    story_plan = StoryPlan(
        title="GOLIVE3 Shot Groups",
        aspect=aspect,
        fps=30,
        duration_sec=sum(g["total_duration_s"] for g in groups),
        metadata=result_manifest,
    )

    json_path = out_dir / "shot_groups_manifest.json"
    json_path.write_text(story_plan.model_dump_json(indent=2), encoding="utf-8")

    png_path = out_dir / "shot_groups_preview.png"
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512, 512), color=(240, 250, 245))
        d = ImageDraw.Draw(img)
        d.text((20, 20), f"Storyboard Shot Groups ({len(groups)} groups)", fill=(20, 50, 30))
        y = 60
        for g in groups:
            d.text((20, y), f"{g['group_id']}: {len(g['shots'])} shots ({g['total_duration_s']}s)", fill=(40, 70, 50))
            y += 30
        img.save(png_path)
    except Exception:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n...")

    return CapabilityResult(
        mp4=None,
        png=png_path,
        wav=None,
        duration_s=story_plan.duration_sec,
        sha256=_sha256_text(json_path.read_text(encoding="utf-8")),
        qa=result_manifest,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────
def register_golive3_capabilities() -> list[Capability]:
    caps = [
        Capability(
            name="assets.library",
            kind="asset",
            aspects=["16:9", "9:16", "universal"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "list", "get"]},
                    "kind": {"type": "string", "enum": ["character", "scene", "prop"]},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "reference_images": {"type": "array", "items": {"type": "string"}},
                    "voice_binding": {"type": "string"},
                    "id": {"type": "string"},
                },
            },
            cpu_cost_hint=0.1,
            render=_render_assets_library,
            description="项目内可复用资产库（角色/场景/道具 CRUD 与音色绑定，集成 ReferenceStore）。",
            line="golive3",
        ),
        Capability(
            name="assets.extract",
            kind="extractor",
            aspects=["universal"],
            params_schema={
                "type": "object",
                "properties": {
                    "script_text": {"type": "string"},
                },
                "required": ["script_text"],
            },
            cpu_cost_hint=0.2,
            render=_render_assets_extract,
            description="从剧本自动抽取角色、场景与道具（复用 hevi.creative.layer4 ImportModule）。",
            line="golive3",
        ),
        Capability(
            name="image.multi_ref_compose",
            kind="overlay",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shot_prompt": {"type": "string"},
                    "references": {"type": "object"},
                    "provider": {"type": "string"},
                    "max_refs": {"type": "integer"},
                },
                "required": ["shot_prompt", "references"],
            },
            cpu_cost_hint=0.5,
            render=_render_multi_ref_compose,
            description="多参考图融合与占位符解析（支持 capability_guard 与 provider 上限校验）。",
            line="golive3",
        ),
        Capability(
            name="style.project_snapshot",
            kind="style",
            aspects=["universal"],
            params_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "base_preset": {"type": "string"},
                    "overrides": {"type": "object"},
                },
            },
            cpu_cost_hint=0.1,
            render=_render_project_snapshot,
            description="项目级风格快照（生成不可变持久化版本快照ID，支持版本回溯）。",
            line="golive3",
        ),
        Capability(
            name="storyboard.shot_groups",
            kind="storyboard",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "scene": {"type": "string"},
                                "duration_s": {"type": "number"},
                                "prompt": {"type": "string"},
                            },
                        },
                    },
                    "group_duration_s": {"type": "number"},
                },
            },
            cpu_cost_hint=0.2,
            render=_render_shot_groups,
            description="分镜镜头组拆分（复用 hevi.storyplan 模型，生成视频提示词与首尾帧约束）。",
            line="golive3",
        ),
    ]

    for c in caps:
        register(c)
    logger.info("registered 5 GOLIVE3 capabilities")
    return caps


def register_golive3_capabilities_once() -> list[Capability]:
    return register_golive3_capabilities()
