"""渲染后端工厂（对标 ViMax tools/render_backend.py）。

从 YAML 配置的 class_path 动态加载 ImageGenerator / VideoGenerator 类。
比 Hevi 现有的 dynamic_loader.py 更聚焦于图像/视频生成场景。

用法：
    # 从配置创建
    backend = RenderBackend.from_config({
        "image_generator": {
            "class_path": "hevi.director.image_selector.generate_and_select",
            "init_args": {"n_candidates": 3},
        },
        "video_generator": {
            "class_path": "hevi.video.provider_minimax.generate_minimax_clip",
            "init_args": {"resolution": "720p"},
        },
    })

    # 使用
    image = await backend.generate_image(prompt, ref_paths, output_path)
    video = await backend.generate_video(prompt, ref_paths, output_path)
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── 协议定义 ──────────────────────────────────────────────────────────


@runtime_checkable
class ImageGenerator(Protocol):
    """图像生成器协议。"""

    async def generate(
        self,
        prompt: str,
        reference_image_paths: list[Path],
        output_path: Path,
        **kwargs: Any,
    ) -> Path: ...


@runtime_checkable
class VideoGenerator(Protocol):
    """视频生成器协议。"""

    async def generate(
        self,
        prompt: str,
        reference_image_paths: list[Path],
        output_path: Path,
        **kwargs: Any,
    ) -> Path: ...


# ── 函数适配器 ────────────────────────────────────────────────────────


class FunctionImageGenerator:
    """将普通 async 函数适配为 ImageGenerator 协议。"""

    def __init__(self, fn: Callable, init_args: dict[str, Any] | None = None):
        self._fn = fn
        self._init_args = init_args or {}

    async def generate(
        self,
        prompt: str,
        reference_image_paths: list[Path],
        output_path: Path,
        **kwargs: Any,
    ) -> Path:
        merged = {**self._init_args, **kwargs}
        result = await self._fn(
            prompt=prompt,
            reference_images=reference_image_paths,
            output_path=output_path,
            **merged,
        )
        if isinstance(result, Path):
            return result
        return output_path


class FunctionVideoGenerator:
    """将普通 async 函数适配为 VideoGenerator 协议。"""

    def __init__(self, fn: Callable, init_args: dict[str, Any] | None = None):
        self._fn = fn
        self._init_args = init_args or {}

    async def generate(
        self,
        prompt: str,
        reference_image_paths: list[Path],
        output_path: Path,
        **kwargs: Any,
    ) -> Path:
        merged = {**self._init_args, **kwargs}
        result = await self._fn(
            prompt=prompt,
            output_path=output_path,
            reference_images=reference_image_paths,
            **merged,
        )
        if isinstance(result, Path):
            return result
        return output_path


# ── 动态加载 ──────────────────────────────────────────────────────────


def _import_callable(class_path: str) -> Any:
    """从 dotted path 导入可调用对象。

    支持：
      - "module.submodule.ClassName"
      - "module.submodule.function_name"
      - "module.submodule.ClassName.method_name"
    """
    parts = class_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ImportError(f"invalid class_path: {class_path}")

    module_path, attr_name = parts

    try:
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    except (ImportError, AttributeError):
        # 尝试作为 "module.Class.method" 加载
        parts2 = module_path.rsplit(".", 1)
        if len(parts2) == 2:
            module = importlib.import_module(parts2[0])
            cls = getattr(module, parts2[1])
            return getattr(cls, attr_name)
        raise ImportError(f"cannot import: {class_path}")


# ── 渲染后端 ──────────────────────────────────────────────────────────


@dataclass
class RenderBackendConfig:
    """渲染后端配置。"""

    image_generator: dict[str, Any] | None = None
    video_generator: dict[str, Any] | None = None
    working_dir: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> RenderBackendConfig:
        """从 YAML 文件加载配置。"""
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            image_generator=data.get("image_generator"),
            video_generator=data.get("video_generator"),
            working_dir=data.get("working_dir", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_generator": self.image_generator,
            "video_generator": self.video_generator,
            "working_dir": self.working_dir,
        }


@dataclass
class RenderBackend:
    """渲染后端：图像生成器 + 视频生成器。"""

    image_generator: Any | None = None
    video_generator: Any | None = None
    working_dir: Path = field(default_factory=lambda: Path("."))

    @classmethod
    def from_config(cls, config: dict[str, Any] | RenderBackendConfig) -> RenderBackend:
        """从配置字典创建渲染后端。"""
        if isinstance(config, RenderBackendConfig):
            cfg_dict = config.to_dict()
        else:
            cfg_dict = config

        image_gen = None
        video_gen = None

        # 加载图像生成器
        img_cfg = cfg_dict.get("image_generator")
        if img_cfg and img_cfg.get("class_path"):
            try:
                fn = _import_callable(img_cfg["class_path"])
                init_args = img_cfg.get("init_args", {})
                image_gen = FunctionImageGenerator(fn, init_args)
                logger.info("loaded image generator: %s", img_cfg["class_path"])
            except ImportError as e:
                logger.warning("failed to load image generator: %s", e)

        # 加载视频生成器
        vid_cfg = cfg_dict.get("video_generator")
        if vid_cfg and vid_cfg.get("class_path"):
            try:
                fn = _import_callable(vid_cfg["class_path"])
                init_args = vid_cfg.get("init_args", {})
                video_gen = FunctionVideoGenerator(fn, init_args)
                logger.info("loaded video generator: %s", vid_cfg["class_path"])
            except ImportError as e:
                logger.warning("failed to load video generator: %s", e)

        return cls(
            image_generator=image_gen,
            video_generator=video_gen,
            working_dir=Path(cfg_dict.get("working_dir", ".")),
        )

    async def generate_image(
        self,
        prompt: str,
        reference_paths: list[Path] | None = None,
        output_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """生成图像。"""
        if self.image_generator is None:
            raise RuntimeError("no image generator configured")

        refs = reference_paths or []
        if output_path is None:
            self.working_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.working_dir / "generated_image.png"

        return await self.image_generator.generate(prompt, refs, output_path, **kwargs)

    async def generate_video(
        self,
        prompt: str,
        reference_paths: list[Path] | None = None,
        output_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """生成视频。"""
        if self.video_generator is None:
            raise RuntimeError("no video generator configured")

        refs = reference_paths or []
        if output_path is None:
            self.working_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.working_dir / "generated_video.mp4"

        return await self.video_generator.generate(prompt, refs, output_path, **kwargs)

    @property
    def has_image_generator(self) -> bool:
        return self.image_generator is not None

    @property
    def has_video_generator(self) -> bool:
        return self.video_generator is not None


# ── 便捷预设 ──────────────────────────────────────────────────────────


PRESET_PROVIDERS: dict[str, dict[str, Any]] = {
    "minimax": {
        "video_generator": {
            "class_path": "hevi.video.provider_minimax.generate_minimax_clip",
            "init_args": {"resolution": "720p", "duration_s": 5},
        },
    },
    "veo": {
        "video_generator": {
            "class_path": "hevi.video.provider_veo.generate_veo_clip",
            "init_args": {},
        },
    },
    "hyperframes": {
        "image_generator": {
            "class_path": "hevi.video.hyperframes_service.render_html_video",
            "init_args": {},
        },
    },
}


def create_backend_from_preset(preset_name: str, **overrides: Any) -> RenderBackend:
    """从预设创建渲染后端。"""
    if preset_name not in PRESET_PROVIDERS:
        raise ValueError(
            f"unknown preset: {preset_name}. Available: {list(PRESET_PROVIDERS.keys())}"
        )

    cfg = dict(PRESET_PROVIDERS[preset_name])
    cfg.update(overrides)
    return RenderBackend.from_config(cfg)


def list_presets() -> list[str]:
    """列出可用预设。"""
    return sorted(PRESET_PROVIDERS.keys())


# ---------------------------------------------------------------------------
# Hevi provider 适配器：将已有 function-based wrapper 适配为 Protocol
# ---------------------------------------------------------------------------


class DashScopeImageAdapter:
    """将 alibaba_maas_service.generate 适配为 ImageGenerator Protocol。"""

    def __init__(self, model: str = "happyhorse_1_1", **_: Any):
        self._model = model

    async def generate(
        self,
        prompt: str,
        reference_image_paths: list[Path] | None = None,
        output_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        from hevi.video.alibaba_maas_service import alibaba_maas_generate

        if output_path is None:
            output_path = Path("/tmp/hevi_images/generated.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = await alibaba_maas_generate(
            prompt=prompt,
            output_path=output_path,
            model=kwargs.get("model", self._model),
        )
        return result


class WanVideoAdapter:
    """将 alibaba_maas_service 视频生成适配为 VideoGenerator Protocol。"""

    def __init__(self, model: str = "wan_2_7", **_: Any):
        self._model = model

    async def generate(
        self,
        prompt: str,
        reference_image_paths: list[Path] | None = None,
        output_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        from hevi.video.alibaba_maas_service import alibaba_maas_generate

        if output_path is None:
            output_path = Path("/tmp/hevi_videos/generated.mp4")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = await alibaba_maas_generate(
            prompt=prompt,
            output_path=output_path,
            model=kwargs.get("model", self._model),
        )
        return result


def create_render_backend(
    image_provider: str = "dashscope",
    video_provider: str = "wan",
    image_params: dict[str, Any] | None = None,
    video_params: dict[str, Any] | None = None,
    working_dir: str | Path = ".",
) -> RenderBackend:
    """从 Hevi 已有 provider 名称创建 RenderBackend。

    支持的 image_provider: "dashscope"
    支持的 video_provider: "wan"
    """
    image_gen: Any | None = None
    video_gen: Any | None = None

    if image_provider == "dashscope":
        image_gen = DashScopeImageAdapter(**(image_params or {}))
    else:
        raise ValueError(f"Unsupported image provider: {image_provider}")

    if video_provider == "wan":
        video_gen = WanVideoAdapter(**(video_params or {}))
    else:
        raise ValueError(f"Unsupported video provider: {video_provider}")

    return RenderBackend(
        image_generator=image_gen,
        video_generator=video_gen,
        working_dir=Path(working_dir),
    )
