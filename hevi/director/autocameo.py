"""AutoCameo — 参考照片→角色入戏（对标 ViMax autocameo.py）。

允许用户上传个人/宠物照片，将其作为角色插入生成的故事中：
  1. extract_person_from_photo() — 从照片提取人物描述
  2. generate_portrait_triptych() — 生成正面/侧面/背面三联画（保持面部相似度）
  3. integrate_character() — 将角色集成到故事中

关键技术：
  - Image-to-image 转换（保持面部特征）
  - 肖像三联画生成（正面/侧面/背面）
  - 角色身份追踪（跨镜头一致性）
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from hevi.agent_runtime.checkpoint import PipelineCheckpoint
from hevi.director.portrait_triptych import (
    PortraitRegistry,
    generate_portrait_triptych,
)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class PersonInfo:
    """从照片提取的人物信息。"""

    name: str
    description: str
    age_estimate: str = ""
    gender: str = ""
    features: list[str] = field(default_factory=list)
    clothing: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "age_estimate": self.age_estimate,
            "gender": self.gender,
            "features": self.features,
            "clothing": self.clothing,
        }


@dataclass
class CameoCharacter:
    """客串角色（来自用户上传的照片）。"""

    character_id: str
    person_info: PersonInfo
    reference_photo_path: Path
    portrait_registry: Optional[PortraitRegistry] = None
    role_in_story: str = ""  # 在故事中的角色（主角/配角/路人）

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "person_info": self.person_info.to_dict(),
            "reference_photo_path": str(self.reference_photo_path),
            "role_in_story": self.role_in_story,
        }


@dataclass
class AutoCameoConfig:
    """AutoCameo 配置。"""

    working_dir: Path = field(default_factory=lambda: Path(".working_dir/autocameo"))
    portrait_style: str = "realistic"
    max_cameo_characters: int = 3
    face_similarity_threshold: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "working_dir": str(self.working_dir),
            "portrait_style": self.portrait_style,
            "max_cameo_characters": self.max_cameo_characters,
            "face_similarity_threshold": self.face_similarity_threshold,
        }


@dataclass
class AutoCameoResult:
    """AutoCameo 结果。"""

    cameo_characters: list[CameoCharacter] = field(default_factory=list)
    portrait_registry: Optional[PortraitRegistry] = None
    integration_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameo_count": len(self.cameo_characters),
            "characters": [c.to_dict() for c in self.cameo_characters],
            "integration_notes": self.integration_notes,
        }


# ── 管线实现 ──────────────────────────────────────────────────────────


class AutoCameo:
    """AutoCameo 处理器。

    用法：
        autocameo = AutoCameo(config=AutoCameoConfig(), llm_caller=my_llm, image_gen=my_image_gen)
        result = await autocameo.process(
            reference_photos=[Path("me.jpg"), Path("friend.jpg")],
            story_context="一个关于友谊的故事",
        )
    """

    def __init__(
        self,
        config: Optional[AutoCameoConfig] = None,
        llm_caller: Optional[Callable] = None,
        image_gen: Optional[Callable] = None,
    ):
        self.config = config or AutoCameoConfig()
        self.llm_caller = llm_caller
        self.image_gen = image_gen
        self.checkpoint = PipelineCheckpoint(self.config.working_dir)

    async def process(
        self,
        reference_photos: list[Path],
        story_context: str = "",
    ) -> AutoCameoResult:
        """处理参考照片，生成客串角色。

        Args:
            reference_photos: 用户上传的照片路径列表
            story_context: 故事背景（用于确定角色定位）

        Returns:
            AutoCameoResult
        """
        result = AutoCameoResult()

        # 限制数量
        photos = reference_photos[:self.config.max_cameo_characters]

        for i, photo_path in enumerate(photos, 1):
            character_id = f"cameo_{i:02d}"

            # 阶段 1: 提取人物信息
            person_stage = self.checkpoint.stage("extract_person")
            person_data = await self.checkpoint.run_if_missing(
                person_stage,
                character_id,
                lambda p=photo_path: self._extract_person_from_photo(p),
            )
            person_info = PersonInfo(**person_data)

            # 阶段 2: 生成肖像三联画
            portrait_stage = self.checkpoint.stage("generate_portrait")
            portrait_data = await self.checkpoint.run_if_missing(
                portrait_stage,
                character_id,
                lambda p=photo_path, info=person_info: self._generate_portrait(p, info),
            )
            portrait_registry = PortraitRegistry.from_dict(portrait_data)

            # 阶段 3: 确定角色定位
            role = await self._determine_role(person_info, story_context)

            cameo = CameoCharacter(
                character_id=character_id,
                person_info=person_info,
                reference_photo_path=photo_path,
                portrait_registry=portrait_registry,
                role_in_story=role,
            )
            result.cameo_characters.append(cameo)

            result.integration_notes.append(
                f"Added {person_info.name} as {role} (based on uploaded photo)"
            )

        # 合并所有肖像注册表
        if result.cameo_characters:
            result.portrait_registry = self._merge_portrait_registries(
                [c.portrait_registry for c in result.cameo_characters if c.portrait_registry]
            )

        return result

    async def _extract_person_from_photo(self, photo_path: Path) -> dict[str, Any]:
        """从照片提取人物信息。"""
        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

        prompt = f"""分析这张照片中的人物，提取以下信息：

1. 姓名建议（如果不知道，给一个合适的名字）
2. 外貌描述（发型、发色、眼睛颜色、肤色、体型等）
3. 年龄估计
4. 性别
5. 显著特征（眼镜、胡须、纹身等）
6. 服装描述

输出 JSON 格式：
{{
  "name": "名字",
  "description": "详细外貌描述",
  "age_estimate": "20-30岁",
  "gender": "male/female/other",
  "features": ["特征1", "特征2"],
  "clothing": "服装描述"
}}
"""

        if self.llm_caller:
            # 多模态调用（传入图片）
            from hevi.utils.robust_json import robust_json_loads
            raw = await self.llm_caller(
                prompt,
                image_paths=[photo_path],
            )
            data = robust_json_loads(raw)
        else:
            # 无 LLM：默认值
            data = {
                "name": f"Character_{photo_path.stem}",
                "description": "A person with distinctive features",
                "age_estimate": "20-40",
                "gender": "unknown",
                "features": [],
                "clothing": "casual clothing",
            }

        return data

    async def _generate_portrait(
        self,
        reference_photo: Path,
        person_info: PersonInfo,
    ) -> dict[str, Any]:
        """生成肖像三联画（保持面部相似度）。"""
        portrait = await generate_portrait_triptych(
            character_name=person_info.name,
            identifier=person_info.name.lower().replace(" ", "_"),
            description=person_info.description,
            output_dir=self.config.working_dir / "portraits",
            style=self.config.portrait_style,
            image_gen=self.image_gen,
            reference_photo=reference_photo,  # 关键：传入参考照片保持面部相似度
        )

        registry = PortraitRegistry()
        registry.add(portrait)
        return registry.to_dict()

    async def _determine_role(
        self,
        person_info: PersonInfo,
        story_context: str,
    ) -> str:
        """确定角色在故事中的定位。"""
        if not story_context:
            return "supporting"

        prompt = f"""根据以下故事背景，为这个角色确定合适的定位：

角色：{person_info.name}
外貌：{person_info.description}
特征：{", ".join(person_info.features)}

故事背景：
{story_context}

可选定位：
- protagonist (主角)
- supporting (配角)
- cameo (客串)
- narrator (旁白/讲述者)

输出一个词：protagonist/supporting/cameo/narrator
"""
        if self.llm_caller:
            role = await self.llm_caller(prompt)
            role = role.strip().lower()
            if role not in ["protagonist", "supporting", "cameo", "narrator"]:
                role = "supporting"
            return role
        else:
            return "supporting"

    def _merge_portrait_registries(
        self,
        registries: list[PortraitRegistry],
    ) -> PortraitRegistry:
        """合并多个肖像注册表。"""
        merged = PortraitRegistry()
        for reg in registries:
            for portrait in reg.portraits.values():
                merged.add(portrait)
        return merged

    def integrate_into_story(
        self,
        story_text: str,
        cameo_characters: list[CameoCharacter],
    ) -> str:
        """将客串角色集成到故事文本中。"""
        if not cameo_characters:
            return story_text

        # 在故事开头添加角色介绍
        character_intros = ["\n\n## 客串角色\n"]
        for cameo in cameo_characters:
            intro = f"- **{cameo.person_info.name}** ({cameo.role_in_story}): {cameo.person_info.description}"
            character_intros.append(intro)

        return story_text + "\n".join(character_intros)
