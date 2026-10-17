"""Recipe Pack —— 命名工作流配方模式。

对标 SamurAIGPT/Generative-Media-Skills 的 Recipe Pack:
每个 Recipe 是一个声明式的命名工作流，串联多个原子能力（图片生成、
视频生成、音频合成、效果处理等）组成端到端管线。

用法:
    from hevi.video.recipe_pack import RecipePack, get_recipe, list_recipes

    recipe = get_recipe("product_ad_cinematic")
    result = await recipe.execute(
        inputs={"product_image": "product.jpg", "brand_name": "Hevi"},
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class RecipeStepType(str, Enum):
    """工作流步骤类型。"""
    IMAGE_GENERATE = "image_generate"
    IMAGE_EDIT = "image_edit"
    VIDEO_GENERATE = "video_generate"
    VIDEO_EXTEND = "video_extend"
    AUDIO_SYNTHESIZE = "audio_synthesize"
    AUDIO_EFFECTS = "audio_effects"
    VIDEO_CLIP = "video_clip"
    REMOTION_RENDER = "remotion_render"
    LLM_REWRITE = "llm_rewrite"
    UPLOAD = "upload"


@dataclass
class RecipeStep:
    """工作流的一个步骤。"""
    step_type: RecipeStepType
    description: str
    params: dict[str, Any] = field(default_factory=dict)
    input_keys: list[str] = field(default_factory=list)
    output_key: str = ""
    optional: bool = False


@dataclass
class Recipe:
    """命名工作流配方。

    对标 muapi Recipe Pack:声明 inputs、steps、outputs，agent 读取后
    按步骤执行。
    """
    name: str
    description: str
    category: str  # motion / visual / social / audio
    inputs: dict[str, str]  # key → description
    steps: list[RecipeStep]
    outputs: dict[str, str]  # key → description
    estimated_duration_s: int = 0
    estimated_cost_usd: float = 0.0
    tags: list[str] = field(default_factory=list)

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        executor: RecipeExecutor | None = None,
    ) -> dict[str, Any]:
        """执行工作流。"""
        if executor is None:
            executor = RecipeExecutor()
        return await executor.run(self, inputs)


class RecipeExecutor:
    """配方执行器:按步骤调用底层能力。"""

    def __init__(self) -> None:
        self._handlers: dict[RecipeStepType, Callable[..., Awaitable[Any]]] = {}

    def register(self, step_type: RecipeStepType, handler: Callable[..., Awaitable[Any]]) -> None:
        self._handlers[step_type] = handler

    async def run(self, recipe: Recipe, inputs: dict[str, Any]) -> dict[str, Any]:
        """执行配方中的所有步骤。"""
        context = dict(inputs)
        results: dict[str, Any] = {}

        for i, step in enumerate(recipe.steps):
            logger.info("recipe %s step %d/%d: %s (%s)",
                        recipe.name, i+1, len(recipe.steps),
                        step.description, step.step_type.value)

            handler = self._handlers.get(step.step_type)
            if handler is None:
                if step.optional:
                    logger.warning("recipe %s: no handler for %s (optional, skipping)",
                                   recipe.name, step.step_type.value)
                    continue
                raise RuntimeError(
                    f"No handler registered for step type: {step.step_type.value}"
                )

            try:
                # 解析 input_keys 从 context
                step_inputs = {k: context.get(k) for k in step.input_keys if k in context}
                step_inputs.update(step.params)

                result = await handler(**step_inputs)

                if step.output_key:
                    context[step.output_key] = result
                    results[step.output_key] = result

            except Exception as e:
                if step.optional:
                    logger.warning("recipe %s step %d failed (optional): %s",
                                   recipe.name, i+1, e)
                    continue
                raise RuntimeError(
                    f"Recipe {recipe.name} failed at step {i+1} ({step.description}): {e}"
                ) from e

        return results


# ── 内置配方 ──────────────────────────────────────────────────────────────


_RECIPES: dict[str, Recipe] = {}


def register_recipe(recipe: Recipe) -> None:
    _RECIPES[recipe.name] = recipe


def get_recipe(name: str) -> Recipe | None:
    return _RECIPES.get(name)


def list_recipes(category: str | None = None) -> list[Recipe]:
    recipes = list(_RECIPES.values())
    if category:
        recipes = [r for r in recipes if r.category == category]
    return sorted(recipes, key=lambda r: r.name)


def list_recipe_categories() -> list[str]:
    return sorted(set(r.category for r in _RECIPES.values()))


# ── 注册内置配方 ──────────────────────────────────────────────────────────


register_recipe(Recipe(
    name="product_ad_cinematic",
    description="产品照片 → 电影级 5-10s 广告视频",
    category="motion",
    inputs={
        "product_image": "产品照片 URL 或路径",
        "brand_name": "品牌名称",
        "style": "风格关键词（如 luxury, minimal, energetic）",
    },
    steps=[
        RecipeStep(
            step_type=RecipeStepType.IMAGE_EDIT,
            description="增强产品图",
            params={"edit_prompt": "professional product photography, studio lighting"},
            input_keys=["product_image"],
            output_key="enhanced_image",
        ),
        RecipeStep(
            step_type=RecipeStepType.VIDEO_GENERATE,
            description="生成产品广告视频",
            params={"mode": "i2v", "duration_s": 5, "aspect_ratio": "9:16"},
            input_keys=["enhanced_image", "style"],
            output_key="video",
        ),
        RecipeStep(
            step_type=RecipeStepType.AUDIO_SYNTHESIZE,
            description="生成背景音乐",
            params={"style": "cinematic"},
            input_keys=["brand_name"],
            output_key="audio",
            optional=True,
        ),
    ],
    outputs={
        "video": "生成的广告视频",
        "audio": "背景音乐（可选）",
    },
    estimated_duration_s=120,
    estimated_cost_usd=1.5,
    tags=["产品", "广告", "短视频"],
))


register_recipe(Recipe(
    name="character_story_video",
    description="角色一致性动画故事视频",
    category="motion",
    inputs={
        "character_image": "角色参考图",
        "script": "故事脚本",
        "num_scenes": "场景数（默认 3）",
    },
    steps=[
        RecipeStep(
            step_type=RecipeStepType.LLM_REWRITE,
            description="拆分脚本为场景",
            params={"task": "scene_split"},
            input_keys=["script", "num_scenes"],
            output_key="scenes",
        ),
        RecipeStep(
            step_type=RecipeStepType.VIDEO_GENERATE,
            description="逐场景生成视频",
            params={"mode": "i2v", "duration_s": 5},
            input_keys=["character_image", "scenes"],
            output_key="scene_videos",
        ),
    ],
    outputs={
        "scenes": "场景列表",
        "scene_videos": "各场景视频",
    },
    estimated_duration_s=300,
    estimated_cost_usd=5.0,
    tags=["角色", "故事", "动画"],
))


register_recipe(Recipe(
    name="long_to_shorts",
    description="长视频 → N 个短视频（AI 高光提取 + 病毒评分）",
    category="motion",
    inputs={
        "video_path": "长视频路径",
        "num_clips": "提取数量（默认 5）",
        "aspect_ratio": "比例（默认 9:16）",
    },
    steps=[
        RecipeStep(
            step_type=RecipeStepType.VIDEO_CLIP,
            description="AI 智能拆条",
            params={"num_clips": 5, "aspect_ratio": "9:16"},
            input_keys=["video_path", "num_clips", "aspect_ratio"],
            output_key="clips",
        ),
    ],
    outputs={
        "clips": "拆条结果（含评分、标题、路径）",
    },
    estimated_duration_s=180,
    estimated_cost_usd=0.5,
    tags=["拆条", "短视频", "高光"],
))


register_recipe(Recipe(
    name="paper_stop_motion",
    description="纸感定格动画风格视频",
    category="motion",
    inputs={
        "subject": "主题描述",
        "script": "故事脚本",
    },
    steps=[
        RecipeStep(
            step_type=RecipeStepType.IMAGE_GENERATE,
            description="生成纸感角色/场景图",
            params={
                "style": "handcrafted paper cutout, stop-motion animation, "
                         "visible paper texture, layered cardboard, craft aesthetic",
            },
            input_keys=["subject"],
            output_key="paper_assets",
        ),
        RecipeStep(
            step_type=RecipeStepType.VIDEO_GENERATE,
            description="生成定格动画视频",
            params={"mode": "i2v", "duration_s": 5},
            input_keys=["paper_assets", "script"],
            output_key="video",
        ),
    ],
    outputs={
        "paper_assets": "纸感资产图",
        "video": "定格动画视频",
    },
    estimated_duration_s=180,
    estimated_cost_usd=2.0,
    tags=["纸感", "定格动画", "手工"],
))


register_recipe(Recipe(
    name="ugc_video_factory",
    description="自拍 + 产品图 + 脚本 → 10s UGC 竖屏广告",
    category="social",
    inputs={
        "person_image": "人物自拍",
        "product_image": "产品图",
        "script": "广告脚本",
    },
    steps=[
        RecipeStep(
            step_type=RecipeStepType.IMAGE_EDIT,
            description="合成使用场景",
            params={"edit_prompt": "person using product naturally, lifestyle setting"},
            input_keys=["person_image", "product_image"],
            output_key="lifestyle_image",
        ),
        RecipeStep(
            step_type=RecipeStepType.VIDEO_GENERATE,
            description="生成 UGC 风格视频",
            params={"mode": "i2v", "duration_s": 10, "aspect_ratio": "9:16"},
            input_keys=["lifestyle_image", "script"],
            output_key="video",
        ),
    ],
    outputs={
        "lifestyle_image": "生活场景图",
        "video": "UGC 广告视频",
    },
    estimated_duration_s=150,
    estimated_cost_usd=2.5,
    tags=["UGC", "广告", "社交媒体"],
))


register_recipe(Recipe(
    name="seedance_extend",
    description="Seedance 2 视频续写（基于已有视频继续生成）",
    category="motion",
    inputs={
        "request_id": "已有视频的 request_id",
        "extend_prompt": "续写描述",
    },
    steps=[
        RecipeStep(
            step_type=RecipeStepType.VIDEO_EXTEND,
            description="续写视频",
            params={"duration_s": 5},
            input_keys=["request_id", "extend_prompt"],
            output_key="extended_video",
        ),
    ],
    outputs={
        "extended_video": "续写后的视频",
    },
    estimated_duration_s=120,
    estimated_cost_usd=0.5,
    tags=["续写", "Seedance", "延长"],
))
