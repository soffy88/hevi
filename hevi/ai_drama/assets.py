"""Asset bible + image prompts for ai_drama.

One image list carries every reference the shots may use.  Each entry has a
stable ``@图片N`` ref, a kind, a human-readable ``prompt`` (the checkable
brief) and a ``render_prompt`` (what the local keyframe engine actually
receives).  References are assigned in a deterministic order, so the same
script always yields the same @图片N mapping.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schema import PICTURE_REF_RE, iter_shots

logger = logging.getLogger(__name__)

STYLE_TOKENS = {
    "live_action": "cinematic live-action still, natural skin texture, 35mm, muted film grade",
    "anime": "Chinese donghua anime illustration, clean line art, cel shading",
    "3d_cg": "AAA game cinematic 3D render, physically based materials, volumetric light",
    "game_pov": "AAA horror game first-person cinematic, unreal engine 5, photoreal 3D, volumetric fog",
    "ink": "Chinese ink wash painting, rice paper texture, restrained palette",
}

# S21: character sheets used to hard-code anime tokens for every style, which
# made the offline SD-Turbo keyframes look like anime even in ``live_action``.
# Only the anime style gets those tokens now; everything else relies on its own
# style token (or the style card) so 写实 and 风格卡 are not overridden.
ANIME_FILL = "colorful anime illustration, cel shading, "
PORTRAIT_NOUN = {"anime": "anime bust"}


def _style_fill(style: str) -> str:
    return ANIME_FILL if style == "anime" else ""


def _character_ids(script: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in script.get("characters") or [] if c.get("id")]


def _scene_coverage(scene: dict[str, Any]) -> list[str]:
    cov = [str(x) for x in scene.get("coverage") or []]
    return cov or ["大全景"]


def build_assets(script: dict[str, Any]) -> dict[str, Any]:
    """Build the image list from the script.  No pixels are rendered here."""
    style = str(script.get("style") or "live_action")
    tokens = str(script.get("style_prompt") or "").strip() or STYLE_TOKENS.get(
        style, STYLE_TOKENS["live_action"]
    )
    images: list[dict[str, Any]] = []
    n = 0

    def add(**entry: Any) -> str:
        nonlocal n
        n += 1
        ref = f"@图片{n}"
        entry["ref"] = ref
        images.append(entry)
        return ref

    for char in _character_ids(script):
        cid = str(char["id"])
        look = str(char.get("look") or char.get("appearance") or "").strip()
        look_en = str(char.get("render_look_en") or look).strip()
        add(
            kind="character_identity",
            character_id=cid,
            name=str(char.get("name") or cid),
            prompt=(
                f"角色身份板：{look}。正面、侧面、背面全身三视图，加表情栏（平静/惊讶/难过/微笑），"
                "白底纯白背景，全身到鞋子，鞋子写清颜色与款式，同一角色同一套服装。"
            ),
            render_prompt=(
                f"{look_en}, character turnaround sheet, front view, side view, back view, three full body views, "
                f"expression sheet, calm surprised sad smiling, pure white background, full body including shoes, "
                f"same outfit, consistent character design, {_style_fill(style)}{tokens}"
            ),
            width=512, height=512,
            usage=f"角色 {cid} 的身份板；用于所有含该角色的镜头，锁定脸、发型、服装、鞋。",
        )
        add(
            kind="character_portrait",
            character_id=cid,
            name=str(char.get("name") or cid),
            prompt=(
                f"{look} 的胸像特写，正面看镜头，白底纯白背景，柔和均匀光，"
                "表情中性，用于口型镜头与正反打。"
            ),
            render_prompt=(
                f"{look_en}, {PORTRAIT_NOUN.get(style, 'bust portrait')}, one character only, single head, centered, "
                f"neutral expression, soft even light, pure white background, {_style_fill(style)}{tokens}"
            ),
            width=512, height=512,
            usage=f"角色 {cid} 的口型/近景镜头；与身份板同一张脸。",
        )

    for scene in script.get("scenes") or []:
        sid = str(scene.get("scene_id"))
        name = str(scene.get("name") or scene.get("location") or sid)
        light = scene.get("lighting") or {}
        scene_en = str(scene.get("render_en") or name).strip()
        light_text = (
            f"光线方向{light.get('direction', '侧光')}，"
            f"{light.get('hardness', '柔光')}，{light.get('warmth', '冷色')}，"
            f"明暗对比{light.get('contrast', '中等')}"
        )
        for cov in _scene_coverage(scene):
            framing = {
                "大全景": "wide establishing shot of the whole location",
                "正打": "camera from one side of the table facing the other seat, reverse-shot A",
                "反打": "camera from the opposite side of the table facing the first seat, reverse-shot B",
                "中景": "medium shot of the table area",
                "近景": "close shot of a table surface detail",
            }.get(cov, f"{cov} framing")
            add(
                kind="scene",
                scene_id=sid,
                coverage=list(_scene_coverage(scene)),
                name=f"{name}-{cov}",
                prompt=(
                    f"场景 {name}（{scene.get('header', '')}）{cov}，空镜无人，不要出现任何人物或人影。"
                    f"{light_text}。同一场景的多角度保持同一套风格与同一套光。"
                ),
                render_prompt=(
                    f"empty location with no people, no human figures, {framing}, {scene_en}, "
                    f"lighting {light_text}, same set and same light across angles, {tokens}"
                ),
                width=512, height=512,
                usage=f"场景 {sid} 的 {cov} 空镜；对话戏正打/反打/大全景。",
            )
        for prop in scene.get("props") or []:
            pname = str(prop.get("name") or prop.get("id") or "")
            size = prop.get("size_cm")
            add(
                kind="prop",
                scene_id=sid,
                name=pname,
                size_cm=size,
                prompt=(
                    f"道具 {pname}，纯白背景单品，正面，写实际尺寸 {size or '[缺失]'} cm，"
                    "不要手、不要人物、不要文字标签。"
                ),
                render_prompt=(
                    f"single prop {pname}, pure white background, front view, no hands, no people, "
                    f"product still life, scale reference, {tokens}"
                ),
                width=512, height=512,
                usage=f"场景 {sid} 的道具 {pname}；用于插入镜头。",
            )
    return {
        "images": images,
        "style": style,
        "style_prompt": str(script.get("style_prompt") or ""),
        "style_makeup_reference": str(script.get("style_makeup_reference") or ""),
        "aspect": script.get("aspect", "9:16"),
    }


def assign_shot_refs(storyboard: dict[str, Any], assets: dict[str, Any]) -> None:
    """Attach existing asset refs to shots (mutates the storyboard)."""
    images = assets.get("images") or []
    by_character: dict[str, dict[str, str]] = {}
    by_scene: dict[str, dict[str, str]] = {}
    for img in images:
        if img.get("kind") in ("character_identity", "character_portrait") and img.get("character_id"):
            slot = "identity" if img["kind"] == "character_identity" else "portrait"
            by_character.setdefault(str(img["character_id"]), {})[slot] = str(img["ref"])
        if img.get("kind") == "scene" and img.get("scene_id"):
            cov = str(img.get("name") or "").rsplit("-", 1)[-1]
            by_scene.setdefault(str(img["scene_id"]), {})[cov] = str(img["ref"])
    for shot in iter_shots(storyboard):
        if shot.get("refs"):
            continue
        refs: list[str] = []
        scene_refs = by_scene.get(str(shot.get("scene_id")), {})
        coverage = str(shot.get("coverage") or "")
        if coverage and coverage in scene_refs:
            refs.append(scene_refs[coverage])
        elif scene_refs:
            refs.append(scene_refs.get("大全景") or next(iter(scene_refs.values())))
        mode = str(shot.get("mode") or "talking")
        if mode in ("talking", "reaction", "insert") or shot.get("dialogue"):
            cid = str(shot.get("character_id") or (shot.get("characters") or [None])[0] or "")
            if cid in by_character:
                refs.append(by_character[cid]["portrait"])
                if mode != "talking" and by_character[cid].get("identity"):
                    refs.append(by_character[cid]["identity"])
        for ref in shot.get("extra_refs") or []:
            if str(ref) not in refs:
                refs.append(str(ref))
        shot["refs"] = refs


def render_assets(
    assets: dict[str, Any],
    out_dir: Path,
    *,
    seed: int = 42,
    width: int = 512,
    height: int = 896,
    engine_name: str = "sdturbo_cpu_fp16",
    force: bool = False,
) -> dict[str, Any]:
    """Render every asset image with the local SD-Turbo engine.

    Returns a mapping ref -> path.  Missing engine/model raises; the caller can
    fall back to a procedural plate only when it declares that fallback.
    """
    from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine

    if engine_name == "sdturbo_cpu_fp16":
        engine_name = "sdturbo_cpu"  # avoid importing the huobao package (circular at capability import)
    engine = resolve_keyframe_engine(engine_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for i, img in enumerate(assets.get("images") or []):
        ref = str(img["ref"])
        stem = PICTURE_REF_RE.fullmatch(ref)
        name = f"pic{stem.group(1).zfill(2) if stem else i:0>2}_{img.get('kind', 'image')}.png"
        path = out_dir / name
        if force or not path.is_file() or path.stat().st_size == 0:
            prompt = str(img.get("render_prompt") or img.get("prompt") or "cinematic still")
            engine.generate(
                prompt_en=prompt,
                negative="text, watermark, logo, subtitles, duplicate, two heads, multiple faces, deformed hands",
                width=int(img.get("width") or width),
                height=int(img.get("height") or height),
                steps=2,
                seed=seed + i * 17,
                output_path=path,
            )
        img["path"] = str(path)
        paths[ref] = str(path)
    return paths


def save_assets(assets: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def shot_prompt(shot: dict[str, Any], style: str, *, game_pov: bool = False) -> str:
    """Compile one shot's generation prompt.

    Order follows the brief: reference usage first, then staging, then action,
    then camera/size/angle, then light; sound and dialogue stay outside (they
    are not visual prompt text).  Every @图片N gets an explicit use clause.
    """
    parts: list[str] = []
    if shot.get("refs"):
        usage = ", ".join(f"{ref} 用于{shot.get('ref_usage', {}).get(ref, '角色/场景参考')}" for ref in shot["refs"])
        parts.append(f"参考图：{usage}。")
    if shot.get("staging"):
        parts.append(f"站位：{shot['staging']}。")
    if shot.get("action"):
        parts.append(f"动作：{shot['action']}。")
    if shot.get("camera"):
        parts.append(f"镜头：{shot['camera']}。")
    if shot.get("lighting"):
        parts.append(f"光影：{shot['lighting']}。")
    if game_pov and shot.get("mode") == "pov":
        info = shot.get("pov") or {}
        parts.append(
            f"第一人称 POV：我在{info.get('where')}，正在看{info.get('looking')}，"
            f"接下来{info.get('next_move')}。可见身体：{info.get('body') or '我的手、袖子和鞋'}。"
        )
    if game_pov and shot.get("mode") == "third_person_pass":
        comp = shot.get("composition") or {}
        parts.append(
            f"第三人称过场：主角在{comp.get('protagonist')}，对方在{comp.get('other')}，"
            f"机位{comp.get('camera')}。"
        )
    tokens = STYLE_TOKENS.get(style, STYLE_TOKENS["live_action"])
    parts.append(tokens + "。")
    return " ".join(parts)
