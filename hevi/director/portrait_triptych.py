"""角色肖像三联画（对标 ViMax character_portraits_generator.py）。

为每个角色生成三视角参考图（正面/侧面/背面），确保多镜头角色一致性。

流程：
  1. 从角色描述生成正面肖像（front portrait）
  2. 以正面肖像为参考，生成侧面肖像（side portrait）
  3. 以正面肖像为参考，生成背面肖像（back portrait）
  4. 所有后续图像生成均使用三联画作为参考

三联画存储在 working_dir/character_portraits/<character_name>/ 下。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class PortraitView:
    """单个视角的肖像。"""

    view: str  # "front" | "side" | "back"
    path: Path
    description: str = ""
    generation_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "view": self.view,
            "path": str(self.path),
            "description": self.description,
            "generation_prompt": self.generation_prompt,
        }


@dataclass
class CharacterPortrait:
    """角色完整三联画。"""

    name: str
    identifier: str  # 在剧本中的标识符
    physical_description: str
    front: PortraitView | None = None
    side: PortraitView | None = None
    back: PortraitView | None = None
    style: str = ""

    @property
    def all_views(self) -> list[PortraitView]:
        views = [self.front, self.side, self.back]
        return [v for v in views if v is not None]

    @property
    def reference_paths(self) -> list[Path]:
        return [v.path for v in self.all_views if v.path.exists()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "identifier": self.identifier,
            "physical_description": self.physical_description,
            "front": self.front.to_dict() if self.front else None,
            "side": self.side.to_dict() if self.side else None,
            "back": self.back.to_dict() if self.back else None,
            "style": self.style,
            "reference_paths": [str(p) for p in self.reference_paths],
        }


@dataclass
class PortraitRegistry:
    """所有角色的肖像注册表。"""

    portraits: dict[str, CharacterPortrait] = field(default_factory=dict)

    def register(self, portrait: CharacterPortrait) -> None:
        self.portraits[portrait.identifier] = portrait

    def get(self, identifier: str) -> CharacterPortrait | None:
        return self.portraits.get(identifier)

    def get_reference_paths(self, identifiers: list[str]) -> list[Path]:
        """获取指定角色的所有参考图路径。"""
        paths: list[Path] = []
        for ident in identifiers:
            p = self.portraits.get(ident)
            if p:
                paths.extend(p.reference_paths)
        return paths

    def to_dict(self) -> dict[str, Any]:
        return {
            ident: cp.to_dict()
            for ident, cp in self.portraits.items()
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortraitRegistry:
        registry = cls()
        for ident, cp_data in data.items():
            cp = CharacterPortrait(
                name=cp_data.get("name", ident),
                identifier=ident,
                physical_description=cp_data.get("physical_description", ""),
                style=cp_data.get("style", ""),
            )
            for view_name in ("front", "side", "back"):
                vdata = cp_data.get(view_name)
                if vdata:
                    setattr(cp, view_name, PortraitView(
                        view=vdata.get("view", view_name),
                        path=Path(vdata.get("path", "")),
                        description=vdata.get("description", ""),
                        generation_prompt=vdata.get("generation_prompt", ""),
                    ))
            registry.register(cp)
        return registry

    def save(self, path: Path) -> None:
        """保存注册表到 JSON。"""
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> PortraitRegistry:
        """从 JSON 加载注册表。"""
        import json
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


# ── 提示词模板 ────────────────────────────────────────────────────────

_FRONT_PROMPT_TEMPLATE = (
    "Full body character reference sheet, front view, facing camera directly. "
    "{description}. "
    "Standing in a neutral T-pose. "
    "Clean white background, studio lighting, even illumination. "
    "Style: {style}. "
    "High detail, photorealistic quality."
)

_SIDE_PROMPT_TEMPLATE = (
    "Full body character reference sheet, side profile view, facing right. "
    "{description}. "
    "Standing in a neutral pose. "
    "Clean white background, studio lighting, even illumination. "
    "Must match the character in the reference image exactly. "
    "Style: {style}. "
    "High detail, photorealistic quality."
)

_BACK_PROMPT_TEMPLATE = (
    "Full body character reference sheet, back view, facing away from camera. "
    "{description}. "
    "Standing in a neutral pose. "
    "Clean white background, studio lighting, even illumination. "
    "Must match the character in the reference image exactly. "
    "Style: {style}. "
    "High detail, photorealistic quality."
)


def build_portrait_prompt(
    view: str,
    description: str,
    style: str = "realistic",
) -> str:
    """构建肖像生成提示词。"""
    templates = {
        "front": _FRONT_PROMPT_TEMPLATE,
        "side": _SIDE_PROMPT_TEMPLATE,
        "back": _BACK_PROMPT_TEMPLATE,
    }
    template = templates.get(view, _FRONT_PROMPT_TEMPLATE)
    return template.format(description=description, style=style)


# ── 生成器协议 ────────────────────────────────────────────────────────

ImageGenFn = Callable[
    [str, list[Path], Path],
    Coroutine[Any, Any, Path],
]
"""图像生成函数签名：(prompt, reference_paths, output_path) → output_path"""


async def _default_image_gen(
    prompt: str,
    references: list[Path],
    output_path: Path,
) -> Path:
    """默认图像生成器（占位，实际使用时注入 provider）。"""
    # 创建一个占位文件（实际使用时替换为真实图像生成）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 写一个 1x1 PNG 占位
    output_path.write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        b'\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02'
        b'\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx'
        b'\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    logger.info(
        "placeholder image gen: prompt=%d chars, refs=%d, output=%s",
        len(prompt), len(references), output_path,
    )
    return output_path


# ── 三联画生成 ────────────────────────────────────────────────────────


async def generate_portrait_view(
    *,
    character_name: str,
    identifier: str,
    description: str,
    view: str,
    output_dir: Path,
    style: str = "realistic",
    reference_images: list[Path] | None = None,
    image_gen: ImageGenFn | None = None,
) -> PortraitView:
    """生成单个视角的肖像。"""
    gen_fn = image_gen or _default_image_gen
    prompt = build_portrait_prompt(view, description, style)
    output_path = output_dir / identifier / f"{view}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    refs = reference_images or []
    result_path = await gen_fn(prompt, refs, output_path)

    return PortraitView(
        view=view,
        path=result_path,
        description=description,
        generation_prompt=prompt,
    )


async def generate_portrait_triptych(
    *,
    character_name: str,
    identifier: str,
    description: str,
    output_dir: Path,
    style: str = "realistic",
    image_gen: ImageGenFn | None = None,
    reference_photo: Path | None = None,
) -> CharacterPortrait:
    """生成角色三联画肖像。

    Args:
        character_name: 角色名称
        identifier: 角色在剧本中的标识符
        description: 外貌描述
        output_dir: 输出根目录
        style: 画风
        image_gen: 图像生成函数（注入 provider）
        reference_photo: 参考照片（AutoCameo 模式）

    Returns:
        CharacterPortrait
    """
    portrait = CharacterPortrait(
        name=character_name,
        identifier=identifier,
        physical_description=description,
        style=style,
    )

    # 如果有参考照片，用作正面肖像的参考
    front_refs: list[Path] = []
    if reference_photo and reference_photo.exists():
        front_refs = [reference_photo]

    # 1. 生成正面肖像
    portrait.front = await generate_portrait_view(
        character_name=character_name,
        identifier=identifier,
        description=description,
        view="front",
        output_dir=output_dir,
        style=style,
        reference_images=front_refs,
        image_gen=image_gen,
    )

    # 2. 以正面肖像为参考，并行生成侧面和背面
    side_refs = [portrait.front.path]
    back_refs = [portrait.front.path]

    side_task = generate_portrait_view(
        character_name=character_name,
        identifier=identifier,
        description=description,
        view="side",
        output_dir=output_dir,
        style=style,
        reference_images=side_refs,
        image_gen=image_gen,
    )
    back_task = generate_portrait_view(
        character_name=character_name,
        identifier=identifier,
        description=description,
        view="back",
        output_dir=output_dir,
        style=style,
        reference_images=back_refs,
        image_gen=image_gen,
    )

    portrait.side, portrait.back = await asyncio.gather(side_task, back_task)

    logger.info(
        "portrait triptych done: %s (%s) → %d views",
        character_name, identifier, len(portrait.all_views),
    )
    return portrait


async def generate_all_portraits(
    characters: list[dict[str, Any]],
    output_dir: Path,
    *,
    style: str = "realistic",
    image_gen: ImageGenFn | None = None,
    existing_registry: PortraitRegistry | None = None,
) -> PortraitRegistry:
    """批量生成所有角色的三联画。

    Args:
        characters: [{"name": "John", "identifier": "john", "description": "...", "reference_photo": "..."}]
        output_dir: 肖像输出根目录
        style: 画风
        image_gen: 图像生成函数
        existing_registry: 已有注册表（跳过已存在的角色）

    Returns:
        PortraitRegistry
    """
    registry = existing_registry or PortraitRegistry()

    # 过滤已存在的角色
    to_generate = [
        c for c in characters
        if c.get("identifier", c.get("name", "")) not in registry.portraits
    ]

    if not to_generate:
        logger.info("all %d characters already have portraits", len(characters))
        return registry

    logger.info(
        "generating portraits for %d/%d characters",
        len(to_generate), len(characters),
    )

    # 并行生成所有角色的三联画
    tasks = []
    for char in to_generate:
        ref_photo = None
        if char.get("reference_photo"):
            ref_photo = Path(char["reference_photo"])

        task = generate_portrait_triptych(
            character_name=char.get("name", ""),
            identifier=char.get("identifier", char.get("name", "")),
            description=char.get("description", ""),
            output_dir=output_dir,
            style=style,
            image_gen=image_gen,
            reference_photo=ref_photo,
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, CharacterPortrait):
            registry.register(result)
        elif isinstance(result, Exception):
            logger.error("portrait generation failed: %s", result)

    # 保存注册表
    registry.save(output_dir / "character_portraits_registry.json")

    return registry
