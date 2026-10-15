"""H3 prompt compiler extension for kids manifest (FIX-14 §3.3 规则 3).
编译单镜 prompt，强制以 Style Bible 四段逐字开头。
"""

from __future__ import annotations

from typing import Any
from hevi.prompt.h3_compiler import (
    scene_block,
    character_block,
    action_block,
    dialogue_block,
    H3Render,
)


def style_bible_preamble(style_bible: Any) -> str:
    """Style Bible 四段逐字前置。"""
    art = getattr(style_bible, "art_style", "") or ""
    cam = getattr(style_bible, "camera_language", "") or ""
    col = getattr(style_bible, "color_grade", "") or ""
    neg = getattr(style_bible, "negative", "") or ""
    return f"【美术风格】{art}\n【镜头语言】{cam}\n【调色】{col}\n【负面约束】{neg}\n"


def compile_shot_prompt(manifest: Any, shot_index: int) -> str:
    """编译指定镜号的 prompt，必须以 Style Bible 四段逐字开头。"""
    shot = next((s for s in manifest.shots if s.shot_index == shot_index), None)
    if not shot:
        raise ValueError(f"Shot index {shot_index} not found in manifest")

    preamble = style_bible_preamble(manifest.style_bible)

    # 构造 H3 镜头内容
    scene_name = "幼儿故事场景"
    scene_desc = getattr(manifest.scenes[0], "location", "") if manifest.scenes else ""
    s_block = scene_block(scene_name=scene_name, scene_description=scene_desc)
    if shot.camera:
        s_block += f" 机位:{shot.camera}。"

    # 角色映射
    cast = {c.name: i + 1 for i, c in enumerate(manifest.characters)}
    char_blocks = [character_block(name=c.name, s_no=i + 1, anchor=c.anchor_ref or "") for i, c in enumerate(manifest.characters)]
    if not char_blocks:
        char_blocks = [character_block(name="人物", s_no=1)]

    action = action_block(visual_prompt=shot.framing or "生动柔和动态")

    dialogue = ""
    if shot.line:
        d_name = manifest.characters[0].name if manifest.characters else "主角"
        dialogue = f"\n【对白】\n{dialogue_block(name=d_name, s_no=1, text=shot.line)}"

    body = "".join([s_block, *char_blocks, action, dialogue])
    return preamble + body


def validate_style_bible_preamble(prompt: str, style_bible: Any) -> list[str]:
    """校验 prompt 是否逐字包含 Style Bible 四段。"""
    errors: list[str] = []
    preamble = style_bible_preamble(style_bible)
    parts = preamble.strip().split("\n")
    for part in parts:
        if part and part not in prompt:
            errors.append(f"Style Bible 段未逐字前置包含: {part[:40]}")
    if not prompt.startswith("【美术风格】"):
        errors.append("Prompt 必须以【美术风格】开头")
    return errors
