"""L6 场景与画面生成 —— shotlist + character_bible → 帧资产(frame_manifest.json)。
见 HEVI-SPEC-01 §7。

两级资产结构(§7.1):
  1. 场景底图(SceneAsset):同 scene_id 的多个 shot 共用一张,省成本 + 保证背景一致。
     跨 run 的内容寻址复用留给 vault 资产库(EXEC-01 M2),这里只做单次 run 内去重。
  2. shot 帧(ShotFrame):场景底图 + 角色(IP-Adapter 注入参考图)+ 动作 prompt。
     P1 限制:多角色同框的 shot 只用 shot.characters[0](首个角色)做 IP-Adapter
     条件,尚不支持多角色同框一致性(需要多参考图区域控制,留待后续)。

G6 视觉门(gate_frame_manifest):
  - CLIP 相似度:生成帧 vs visual_prompt(hevi.subjects.subject_embed 文本-图像跨模态)
  - 角色一致性:生成帧 vs 角色 ref_image 的 CLIP 图像-图像相似度
    (P1 简化:通用视觉向量,非人脸专用 —— 同 subject_embed 模块本身的既有简化)
  - VLM 年代穿帮审(本地 qwen2.5vl,复用 L5 同款 provider)

降级链(§7.3,任何情况下不允许开天窗):
  reroll ≤3 次(保留角色条件)→ 丢角色纯场景空镜 → 复用相邻场景底图 + 缓推镜头。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from hevi.subjects.subject_embed import cosine_similarity, subject_embed, text_embed
from hevi.tongjian.chapter_ir import _extract_json_obj
from hevi.tongjian.schemas import (
    CharacterBible,
    Constitution,
    FrameManifest,
    GateResult,
    LayerConfig,
    SceneAsset,
    Script,
    Shot,
    ShotFrame,
    ShotList,
)

logger = logging.getLogger(__name__)

_CLIP_SCORE_THRESHOLD = 0.20  # CLIP 文本-图像相似度低于此值判定"跑题"
_CHARACTER_CONSISTENCY_THRESHOLD = 0.55  # 帧 vs ref_image 相似度低于此值判定"不像"
_MAX_REROLLS = 3
_DEFAULT_IP_ADAPTER_WEIGHT = 0.6

_ERA_AUDIT_PROMPT_TEMPLATE = """你是历史短片年代画面审核员。判断这张画面是否存在年代穿帮元素
(如眼镜、纽扣、现代建筑、电线、塑料制品等不属于该历史时期的物品)。

画面描述: {visual_prompt}

只输出 JSON: {{"passes": true/false, "violations": ["..."]}}"""


# ── 场景底图(§7.1 步骤1)────────────────────────────────────────────────────


def _scene_prompt(shots: list[Shot], constitution: Constitution) -> str:
    """场景底图 prompt:不含角色,只描述背景/环境。取同 scene_id 下第一个有
    visual_prompt 的 shot 作为背景基调,角色由 IP-Adapter 在 shot 帧阶段单独注入。
    """
    sample = next((s.visual_prompt for s in shots if s.visual_prompt), "")
    return (
        f"{constitution.visual_style.art_direction}风格历史场景空镜,{sample}。"
        "无人物,背景环境,光线氛围突出。"
    )


def _seed_for(key: str, variant: int = 0) -> int:
    digest = hashlib.sha256(f"{key}:{variant}".encode()).hexdigest()
    return int(digest[:8], 16)


async def generate_scene_assets(
    shotlist: ShotList,
    constitution: Constitution,
    *,
    output_dir: Path,
    image_gen: Any = None,
) -> dict[str, SceneAsset]:
    """spec §7.1:同 scene_id 生成一次场景底图,供该 scene 下所有 shot 复用。

    以进程内字典去重(同一次 run 内同 scene_id 只生成一次)。生成失败的 scene_id
    不出现在返回字典里 —— 调用方(build_frame_manifest)据此走降级链。
    """
    if image_gen is None:
        from obase.provider_registry import ProviderRegistry

        image_gen = ProviderRegistry.get().image_gen("sdxl_local")

    output_dir.mkdir(parents=True, exist_ok=True)
    shots_by_scene: dict[str, list[Shot]] = {}
    for shot in shotlist.shots:
        shots_by_scene.setdefault(shot.scene_id, []).append(shot)

    scenes: dict[str, SceneAsset] = {}
    for scene_id, shots in shots_by_scene.items():
        prompt = _scene_prompt(shots, constitution)
        seed = _seed_for(f"scene:{scene_id}")
        image_path = output_dir / f"scene_{scene_id.lower()}.png"
        try:
            await image_gen(prompt=prompt, output_path=image_path, seed=seed, extra={})
        except Exception as e:
            logger.warning("场景 %s 底图生成失败: %s", scene_id, e)
            continue
        scenes[scene_id] = SceneAsset(
            scene_id=scene_id,
            image_path=str(image_path),
            prompt=prompt,
            seed=seed,
        )

    return scenes


# ── shot 帧生成 + 打分(§7.1 步骤2、§7.3)────────────────────────────────────


def _lead_character(shot: Shot, character_bible: CharacterBible):
    if not shot.characters:
        return None
    by_id = {e.character_id: e for e in character_bible.characters}
    return by_id.get(shot.characters[0])


async def _render_attempt(
    shot: Shot,
    scene_asset: SceneAsset,
    character_bible: CharacterBible,
    *,
    output_dir: Path,
    variant: int,
    with_character: bool,
    image_gen: Any,
) -> Path:
    frame_path = output_dir / f"{shot.shot_id.lower()}_v{variant}.png"
    prompt = f"{scene_asset.prompt} {shot.visual_prompt}".strip()
    seed = _seed_for(shot.shot_id, variant)
    extra: dict[str, Any] = {}

    lead = _lead_character(shot, character_bible) if with_character else None
    if lead is not None and lead.ref_image:
        weight = _DEFAULT_IP_ADAPTER_WEIGHT
        if lead.gen_lock:
            weight = lead.gen_lock.get("ip_adapter_weight", weight)
        extra["ip_adapter_image"] = lead.ref_image
        extra["ip_adapter_weight"] = weight

    await image_gen(prompt=prompt, output_path=frame_path, seed=seed, extra=extra)
    return frame_path


async def _call_vlm_json(vlm: Any, prompt: str, image_path: Path) -> dict[str, Any]:
    resp = await vlm(
        messages=[{"role": "user", "content": prompt}],
        image_paths=[str(image_path)],
        max_tokens=300,
    )
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    return _extract_json_obj(content)


async def _score_frame(
    frame_path: Path,
    shot: Shot,
    character_bible: CharacterBible,
    *,
    vlm: Any,
) -> tuple[float, float | None, bool]:
    """返回 (clip_score, character_consistency_or_None, passed_vlm_audit)。"""
    clip_score = 0.0
    consistency: float | None = None
    passed_audit = True

    try:
        frame_vec = subject_embed(image_path=frame_path, kind="style")
        if shot.visual_prompt:
            clip_score = cosine_similarity(frame_vec, text_embed(shot.visual_prompt))
        lead = _lead_character(shot, character_bible)
        if lead is not None and lead.ref_image and Path(lead.ref_image).exists():
            ref_vec = subject_embed(image_path=lead.ref_image, kind="style")
            consistency = cosine_similarity(frame_vec, ref_vec)
    except Exception as e:
        logger.warning("镜头 %s CLIP 评分失败: %s", shot.shot_id, e)

    try:
        audit_prompt = _ERA_AUDIT_PROMPT_TEMPLATE.format(visual_prompt=shot.visual_prompt)
        audit = await _call_vlm_json(vlm, audit_prompt, frame_path)
        passed_audit = bool(audit.get("passes", True))
    except Exception as e:
        logger.warning("镜头 %s VLM 年代审调用失败,视为通过: %s", shot.shot_id, e)

    return clip_score, consistency, passed_audit


async def render_shot(
    shot: Shot,
    scene_asset: SceneAsset,
    character_bible: CharacterBible,
    fallback_scene: SceneAsset | None,
    *,
    output_dir: Path,
    image_gen: Any = None,
    vlm: Any = None,
    max_rerolls: int = _MAX_REROLLS,
) -> ShotFrame:
    """单 shot 的完整生成 + 打分 + 降级链(spec §7.3)。"""
    if image_gen is None:
        from obase.provider_registry import ProviderRegistry

        image_gen = ProviderRegistry.get().image_gen("sdxl_local")
    if vlm is None:
        from obase.provider_registry import ProviderRegistry

        vlm = ProviderRegistry.get().vlm("default")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 阶段1:reroll ≤ max_rerolls 次(保留角色 IP-Adapter 条件)
    for variant in range(max_rerolls):
        try:
            frame_path = await _render_attempt(
                shot,
                scene_asset,
                character_bible,
                output_dir=output_dir,
                variant=variant,
                with_character=True,
                image_gen=image_gen,
            )
        except Exception as e:
            logger.warning("镜头 %s 第%d次生成失败: %s", shot.shot_id, variant, e)
            continue

        clip_score, consistency, passed_audit = await _score_frame(
            frame_path,
            shot,
            character_bible,
            vlm=vlm,
        )
        ok_clip = clip_score >= _CLIP_SCORE_THRESHOLD
        ok_consistency = consistency is None or consistency >= _CHARACTER_CONSISTENCY_THRESHOLD
        if ok_clip and ok_consistency and passed_audit:
            return ShotFrame(
                shot_id=shot.shot_id,
                scene_id=shot.scene_id,
                frame_path=str(frame_path),
                characters=shot.characters,
                clip_score=clip_score,
                character_consistency=consistency,
                passed_vlm_audit=passed_audit,
            )
        logger.info(
            "镜头 %s 第%d次未达标(clip=%.2f consistency=%s audit=%s),reroll",
            shot.shot_id,
            variant,
            clip_score,
            consistency,
            passed_audit,
        )

    # 阶段2:丢角色,纯场景空镜(旁白型 shot 完全成立,spec §7.3)
    try:
        frame_path = await _render_attempt(
            shot,
            scene_asset,
            character_bible,
            output_dir=output_dir,
            variant=max_rerolls,
            with_character=False,
            image_gen=image_gen,
        )
        clip_score, _, passed_audit = await _score_frame(frame_path, shot, character_bible, vlm=vlm)
        return ShotFrame(
            shot_id=shot.shot_id,
            scene_id=shot.scene_id,
            frame_path=str(frame_path),
            characters=[],
            clip_score=clip_score,
            character_consistency=None,
            passed_vlm_audit=passed_audit,
            degraded=True,
            degrade_reason="角色一致性/CLIP相似度多次未达标或生成失败,降级为纯场景空镜",
        )
    except Exception as e:
        logger.warning("镜头 %s 场景空镜降级也失败: %s", shot.shot_id, e)

    # 阶段3:复用相邻场景底图 + 缓推镜头 —— 任何情况下不允许开天窗
    reuse_scene = fallback_scene or scene_asset
    return ShotFrame(
        shot_id=shot.shot_id,
        scene_id=shot.scene_id,
        frame_path=reuse_scene.image_path,
        characters=[],
        clip_score=0.0,
        character_consistency=None,
        passed_vlm_audit=None,
        degraded=True,
        degrade_reason="场景生成失败,复用相邻场景底图 + 缓推镜头",
    )


# ── 主入口 + G6 门 ───────────────────────────────────────────────────────────


async def build_frame_manifest(
    shotlist: ShotList,
    character_bible: CharacterBible,
    constitution: Constitution,
    *,
    output_dir: Path,
    image_gen: Any = None,
    vlm: Any = None,
) -> tuple[FrameManifest, GateResult]:
    """L6 主入口:场景底图 → 逐 shot 帧(含降级链)→ G6 门。"""
    scenes = await generate_scene_assets(
        shotlist,
        constitution,
        output_dir=output_dir,
        image_gen=image_gen,
    )

    frames: list[ShotFrame] = []
    prev_used_scene: SceneAsset | None = None
    for shot in shotlist.shots:
        scene_asset = scenes.get(shot.scene_id)
        if scene_asset is None:
            if prev_used_scene is None:
                frames.append(
                    ShotFrame(
                        shot_id=shot.shot_id,
                        scene_id=shot.scene_id,
                        frame_path="",
                        degraded=True,
                        degrade_reason="场景底图生成失败且无可复用的相邻场景",
                    )
                )
                continue
            scene_asset = prev_used_scene

        frame = await render_shot(
            shot,
            scene_asset,
            character_bible,
            prev_used_scene,
            output_dir=output_dir,
            image_gen=image_gen,
            vlm=vlm,
        )
        frames.append(frame)
        prev_used_scene = scene_asset

    manifest = FrameManifest(scenes=list(scenes.values()), frames=frames)
    result = gate_frame_manifest(manifest, shotlist)
    return manifest, result


def gate_frame_manifest(manifest: FrameManifest, shotlist: ShotList) -> GateResult:
    """G6 门:每个 shot 必须有非空 frame_path(任何情况下不允许开天窗);
    降级/未过 VLM 审只报 warning,不阻塞。
    """
    errors: list[str] = []
    warnings: list[str] = []

    frames_by_shot = {f.shot_id: f for f in manifest.frames}
    for shot in shotlist.shots:
        frame = frames_by_shot.get(shot.shot_id)
        if frame is None or not frame.frame_path:
            errors.append(f"镜头 {shot.shot_id} 没有任何可用画面(开天窗)")
            continue
        if frame.degraded:
            warnings.append(f"镜头 {shot.shot_id} 走了降级链: {frame.degrade_reason}")
        if frame.passed_vlm_audit is False:
            warnings.append(f"镜头 {shot.shot_id} 未通过 VLM 年代审")

    total = len(shotlist.shots)
    covered = sum(1 for f in manifest.frames if f.frame_path)
    coverage = (covered / total) if total else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)


async def render_shots(
    shotlist: ShotList,
    character_bible: CharacterBible,
    constitution: Constitution,
    *,
    run_dir: Path,
    script: Script | None = None,
    config: LayerConfig | None = None,
    image_gen: Any = None,
    vlm: Any = None,
) -> FrameManifest:
    """L6 主入口(按 LayerConfig.model 路由,统一只回 FrameManifest):
    - `"cloud_avatar"`:云端 happyhorse 数字人 talking clip(见 scene_render_avatar,frames[].clip_path
      已填,自带配音+口型);需要传 script 取每镜台词。
    - 其它/缺省(如 `"sdxl_local"`):本地 SDXL 静帧(build_frame_manifest)。
    (之前 api/routers/tongjian.py import 的 `render_shots` 此前并不存在——这里补上,兼容旧调用。)
    """
    model = config.model if config else None
    if model == "cloud_avatar":
        from hevi.tongjian.scene_render_avatar import build_frame_manifest_avatar

        if script is None:
            raise ValueError("cloud_avatar 渲染需要 script(逐镜取台词)")
        return await build_frame_manifest_avatar(
            shotlist, script, character_bible, constitution, run_dir=run_dir, config=config
        )
    manifest, _gate = await build_frame_manifest(
        shotlist, character_bible, constitution, output_dir=run_dir, image_gen=image_gen, vlm=vlm
    )
    return manifest
