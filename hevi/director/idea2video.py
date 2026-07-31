"""Idea2Video Pipeline — 一句话出片（对标 ViMax idea2video_pipeline.py）。

流程：
  1. develop_story(idea) → 故事文本
  2. extract_characters(story) → 角色列表
  3. generate_portraits(characters) → 肖像三联画
  4. write_script(story) → 场景剧本
  5. design_storyboard(script) → 分镜
  6. generate_shots(storyboard) → 逐 shot 视频
  7. assemble_final(shots) → 最终视频

每阶段都有 checkpoint 支持断点续跑。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from hevi.agent_runtime.checkpoint import PipelineCheckpoint
from hevi.director.portrait_triptych import (
    PortraitRegistry,
    generate_all_portraits,
)
from hevi.director.camera_tree import CameraTree, construct_camera_tree
from hevi.director.render_backend import RenderBackend

logger = logging.getLogger(__name__)


# ── LLM 调用协议 ──────────────────────────────────────────────────────

LLMCallFn = Callable[
    [str, dict[str, Any] | None],
    Coroutine[Any, Any, Any],
]
"""LLM 调用函数：(prompt, schema) → result"""


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class Idea2VideoConfig:
    """Idea2Video 配置。"""

    working_dir: Path = field(default_factory=lambda: Path(".working_dir/idea2video"))
    style: str = "realistic"
    max_scenes: int = 5
    max_shots_per_scene: int = 8
    fps: int = 24
    resolution: str = "720p"
    aspect_ratio: str = "16:9"

    def to_dict(self) -> dict[str, Any]:
        return {
            "working_dir": str(self.working_dir),
            "style": self.style,
            "max_scenes": self.max_scenes,
            "max_shots_per_scene": self.max_shots_per_scene,
            "fps": self.fps,
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
        }

    @classmethod
    def from_yaml(cls, path: Path) -> Idea2VideoConfig:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            working_dir=Path(data.get("working_dir", ".working_dir/idea2video")),
            style=data.get("style", "realistic"),
            max_scenes=data.get("max_scenes", 5),
            max_shots_per_scene=data.get("max_shots_per_scene", 8),
            fps=data.get("fps", 24),
            resolution=data.get("resolution", "720p"),
            aspect_ratio=data.get("aspect_ratio", "16:9"),
        )


@dataclass
class Idea2VideoResult:
    """Idea2Video 最终结果。"""

    final_video_path: Path
    story_text: str = ""
    characters: list[dict[str, Any]] = field(default_factory=list)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    portrait_registry: dict[str, Any] = field(default_factory=dict)
    camera_tree: dict[str, Any] = field(default_factory=dict)
    shot_paths: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_video_path": str(self.final_video_path),
            "story_text": self.story_text,
            "characters": self.characters,
            "scenes": self.scenes,
            "shot_paths": self.shot_paths,
            "duration_s": self.duration_s,
        }


# ── Pipeline 阶段实现 ─────────────────────────────────────────────────


class Idea2VideoPipeline:
    """一句话出片管线。

    用法：
        pipeline = Idea2VideoPipeline(
            config=Idea2VideoConfig(),
            llm_caller=my_llm,
            render_backend=my_backend,
        )
        result = await pipeline.run("A cat and a dog become best friends")
    """

    def __init__(
        self,
        config: Idea2VideoConfig | None = None,
        llm_caller: LLMCallFn | None = None,
        render_backend: RenderBackend | None = None,
        image_gen: Callable | None = None,
        video_gen: Callable | None = None,
    ):
        self.config = config or Idea2VideoConfig()
        self.llm_caller = llm_caller
        self.render_backend = render_backend
        self.image_gen = image_gen
        self.video_gen = video_gen

        self.checkpoint = PipelineCheckpoint(self.config.working_dir)
        self.config.working_dir.mkdir(parents=True, exist_ok=True)

    def _stages(self) -> list[str]:
        return [
            "develop_story",
            "extract_characters",
            "generate_portraits",
            "write_script",
            "design_storyboard",
            "construct_camera_tree",
            "generate_shots",
            "assemble_final",
        ]

    async def run(
        self,
        idea: str,
        user_requirement: str = "",
        style: str | None = None,
    ) -> Idea2VideoResult:
        """运行完整管线。

        Args:
            idea: 用户输入的概念/想法
            user_requirement: 用户的额外要求
            style: 画风覆盖

        Returns:
            Idea2VideoResult
        """
        if style:
            self.config.style = style

        result = Idea2VideoResult(
            final_video_path=self.config.working_dir / "final_video.mp4",
        )

        # Stage 1: 故事开发
        story_stage = self.checkpoint.stage("develop_story")
        story_data = await self.checkpoint.run_if_missing(
            story_stage, "main",
            lambda: self._develop_story(idea, user_requirement),
            inputs={"idea": idea, "requirement": user_requirement},
        )
        result.story_text = story_data.get("story_text", "")

        # Stage 2: 角色提取
        char_stage = self.checkpoint.stage("extract_characters")
        char_data = await self.checkpoint.run_if_missing(
            char_stage, "main",
            lambda: self._extract_characters(result.story_text),
            inputs={"story_hash": result.story_text[:100]},
        )
        result.characters = char_data.get("characters", [])

        # Stage 3: 肖像生成
        portrait_stage = self.checkpoint.stage("generate_portraits")
        portrait_data = await self.checkpoint.run_if_missing(
            portrait_stage, "main",
            lambda: self._generate_portraits(result.characters),
            inputs={"char_count": len(result.characters)},
        )
        result.portrait_registry = portrait_data.get("registry", {})

        # Stage 4: 剧本编写
        script_stage = self.checkpoint.stage("write_script")
        script_data = await self.checkpoint.run_if_missing(
            script_stage, "main",
            lambda: self._write_script(result.story_text, user_requirement),
            inputs={"story_hash": result.story_text[:100]},
        )
        result.scenes = script_data.get("scenes", [])

        # Stage 5: 分镜设计
        storyboard_stage = self.checkpoint.stage("design_storyboard")
        storyboard_data = await self.checkpoint.run_if_missing(
            storyboard_stage, "main",
            lambda: self._design_storyboard(result.scenes, result.characters, user_requirement),
            inputs={"scene_count": len(result.scenes)},
        )
        shots = storyboard_data.get("shots", [])

        # Stage 6: Camera Tree
        camera_stage = self.checkpoint.stage("construct_camera_tree")
        camera_data = await self.checkpoint.run_if_missing(
            camera_stage, "main",
            lambda: self._construct_camera_tree(shots),
            inputs={"shot_count": len(shots)},
        )
        result.camera_tree = camera_data.get("tree", {})

        # Stage 7: 生成 shots
        gen_stage = self.checkpoint.stage("generate_shots")
        gen_data = await self.checkpoint.run_if_missing(
            gen_stage, "main",
            lambda: self._generate_shots(shots, result.portrait_registry),
            inputs={"shot_count": len(shots)},
        )
        result.shot_paths = gen_data.get("shot_paths", [])

        # Stage 8: 最终装配
        assemble_stage = self.checkpoint.stage("assemble_final")
        assemble_data = await self.checkpoint.run_if_missing(
            assemble_stage, "main",
            lambda: self._assemble_final(result.shot_paths),
            inputs={"shot_count": len(result.shot_paths)},
        )
        result.final_video_path = Path(assemble_data.get("output_path", str(result.final_video_path)))
        result.duration_s = assemble_data.get("duration_s", 0.0)

        # 保存最终结果元数据
        meta_path = self.config.working_dir / "result.json"
        meta_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Idea2Video complete: %s (%.1fs, %d shots)",
            result.final_video_path, result.duration_s, len(result.shot_paths),
        )
        return result

    # ── 各阶段实现 ────────────────────────────────────────────────────

    async def _develop_story(self, idea: str, user_requirement: str) -> dict[str, Any]:
        """阶段 1：从概念生成故事。"""
        prompt = (
            f"Based on the following idea, write a short story suitable for a video.\n\n"
            f"Idea: {idea}\n\n"
            + (f"Requirements: {user_requirement}\n\n" if user_requirement else "")
            + "Write a story with clear beginning, middle, and end. "
            f"Keep it concise, suitable for {self.config.max_scenes} scenes max."
        )

        if self.llm_caller:
            story_text = await self.llm_caller(prompt, None)
            if isinstance(story_text, dict):
                story_text = story_text.get("story", str(story_text))
        else:
            # 无 LLM 时返回概念本身
            story_text = idea

        return {"story_text": str(story_text)}

    async def _extract_characters(self, story_text: str) -> dict[str, Any]:
        """阶段 2：从故事提取角色。"""
        prompt = (
            "Extract all characters from the following story. "
            "For each character, provide: name, identifier (lowercase slug), "
            "physical_description, age, gender.\n\n"
            f"Story:\n{story_text}\n\n"
            "Return as JSON: {\"characters\": [{\"name\": ..., \"identifier\": ..., "
            "\"description\": ..., \"age\": ..., \"gender\": ...}]}"
        )

        if self.llm_caller:
            from hevi.utils.robust_json import robust_json_loads
            raw = await self.llm_caller(prompt, {"type": "object"})
            if isinstance(raw, str):
                data = robust_json_loads(raw)
            else:
                data = raw
        else:
            # 无 LLM：返回空角色列表
            data = {"characters": []}

        characters = data.get("characters", [])
        # 确保每个角色有 identifier
        for c in characters:
            if "identifier" not in c:
                c["identifier"] = c.get("name", "unknown").lower().replace(" ", "_")

        return {"characters": characters}

    async def _generate_portraits(self, characters: list[dict[str, Any]]) -> dict[str, Any]:
        """阶段 3：生成角色肖像三联画。"""
        if not characters:
            return {"registry": {}}

        portraits_dir = self.config.working_dir / "character_portraits"
        registry = await generate_all_portraits(
            characters,
            portraits_dir,
            style=self.config.style,
            image_gen=self.image_gen,
        )

        return {"registry": registry.to_dict()}

    async def _write_script(
        self,
        story_text: str,
        user_requirement: str,
    ) -> dict[str, Any]:
        """阶段 4：编写场景剧本。"""
        prompt = (
            f"Write a screenplay based on the following story.\n\n"
            f"Story:\n{story_text}\n\n"
            + (f"Requirements: {user_requirement}\n\n" if user_requirement else "")
            + f"Limit to {self.config.max_scenes} scenes. "
            "For each scene, provide: slugline (e.g. INT. ROOM - DAY), "
            "environment description, script text.\n\n"
            "Return as JSON: {\"scenes\": [{\"slugline\": ..., "
            "\"environment\": ..., \"script\": ...}]}"
        )

        if self.llm_caller:
            from hevi.utils.robust_json import robust_json_loads
            raw = await self.llm_caller(prompt, {"type": "object"})
            if isinstance(raw, str):
                data = robust_json_loads(raw)
            else:
                data = raw
        else:
            data = {"scenes": [
                {"slugline": "EXT. LOCATION - DAY", "environment": "A generic location", "script": story_text}
            ]}

        return {"scenes": data.get("scenes", [])}

    async def _design_storyboard(
        self,
        scenes: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        user_requirement: str,
    ) -> dict[str, Any]:
        """阶段 5：设计分镜。"""
        prompt = (
            "Design a storyboard for the following screenplay.\n\n"
            f"Scenes: {json.dumps(scenes, ensure_ascii=False)}\n\n"
            f"Characters: {json.dumps([c.get('name', '') for c in characters])}\n\n"
            + (f"Requirements: {user_requirement}\n\n" if user_requirement else "")
            + f"Limit to {self.config.max_shots_per_scene} shots per scene. "
            "For each shot, provide: visual_desc, cam_idx, visible_chars (list of names).\n\n"
            "Return as JSON: {\"shots\": [{\"idx\": 0, \"scene_idx\": 0, "
            "\"visual_desc\": ..., \"cam_idx\": 0, \"visible_chars\": [...]}]}"
        )

        if self.llm_caller:
            from hevi.utils.robust_json import robust_json_loads
            raw = await self.llm_caller(prompt, {"type": "object"})
            if isinstance(raw, str):
                data = robust_json_loads(raw)
            else:
                data = raw
        else:
            # 无 LLM：每个场景一个 shot
            shots = []
            for i, scene in enumerate(scenes):
                shots.append({
                    "idx": i,
                    "scene_idx": i,
                    "visual_desc": scene.get("script", ""),
                    "cam_idx": 0,
                    "visible_chars": [],
                })
            data = {"shots": shots}

        return {"shots": data.get("shots", [])}

    async def _construct_camera_tree(self, shots: list[dict[str, Any]]) -> dict[str, Any]:
        """阶段 6：构建 Camera Tree。"""
        tree = construct_camera_tree(shots)
        return {"tree": tree.to_dict()}

    async def _generate_shots(
        self,
        shots: list[dict[str, Any]],
        portrait_registry: dict[str, Any],
    ) -> dict[str, Any]:
        """阶段 7：生成所有 shot 视频。"""
        shots_dir = self.config.working_dir / "shots"
        shots_dir.mkdir(parents=True, exist_ok=True)

        shot_paths: list[str] = []

        for shot in shots:
            shot_idx = shot.get("idx", len(shot_paths))
            output_path = shots_dir / f"shot_{shot_idx:03d}.mp4"

            # 尝试从 checkpoint 加载
            shot_stage = self.checkpoint.stage(f"shot_{shot_idx}")
            if self.checkpoint.exists(shot_stage, "video"):
                loaded = self.checkpoint.load(shot_stage, "video")
                if loaded and loaded.get("path"):
                    shot_paths.append(loaded["path"])
                    continue

            # 生成视频
            prompt = shot.get("visual_desc", "")
            visible_chars = shot.get("visible_chars", [])

            # 收集参考图
            ref_paths: list[Path] = []
            for char_name in visible_chars:
                char_key = char_name.lower().replace(" ", "_")
                char_data = portrait_registry.get(char_key, {})
                if char_data.get("reference_paths"):
                    ref_paths.extend([Path(p) for p in char_data["reference_paths"]])

            if self.video_gen:
                try:
                    await self.video_gen(
                        prompt=prompt,
                        reference_images=ref_paths,
                        output_path=output_path,
                    )
                except Exception as e:
                    logger.warning("shot %d generation failed: %s", shot_idx, e)
                    # 创建占位
                    output_path.write_bytes(b"")
            elif self.render_backend and self.render_backend.has_video_generator:
                try:
                    await self.render_backend.generate_video(
                        prompt, ref_paths, output_path,
                        fps=self.config.fps,
                        resolution=self.config.resolution,
                    )
                except Exception as e:
                    logger.warning("shot %d generation failed: %s", shot_idx, e)
                    output_path.write_bytes(b"")
            else:
                # 无视频生成器：创建占位
                output_path.write_bytes(b"")

            # 保存 checkpoint
            self.checkpoint.save(
                shot_stage, "video",
                {"path": str(output_path), "shot_idx": shot_idx},
            )
            shot_paths.append(str(output_path))

        return {"shot_paths": shot_paths}

    async def _assemble_final(self, shot_paths: list[str]) -> dict[str, Any]:
        """阶段 8：装配最终视频。"""
        output_path = self.config.working_dir / "final_video.mp4"

        if not shot_paths:
            output_path.write_bytes(b"")
            return {"output_path": str(output_path), "duration_s": 0.0}

        # 尝试用 FFmpeg concat
        valid_paths = [p for p in shot_paths if Path(p).exists() and Path(p).stat().st_size > 0]

        if not valid_paths:
            output_path.write_bytes(b"")
            return {"output_path": str(output_path), "duration_s": 0.0}

        try:
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                for p in valid_paths:
                    esc = str(Path(p).resolve()).replace("'", r"'\''")
                    f.write(f"file '{esc}'\n")
                concat_list = Path(f.name)

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            concat_list.unlink(missing_ok=True)

            if proc.returncode != 0:
                # fallback: re-encode
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                    for p in valid_paths:
                        esc = str(Path(p).resolve()).replace("'", r"'\''")
                        f.write(f"file '{esc}'\n")
                    concat_list = Path(f.name)

                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    str(output_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                concat_list.unlink(missing_ok=True)

        except Exception as e:
            logger.warning("ffmpeg concat failed: %s, using simple copy", e)
            if len(valid_paths) == 1:
                import shutil
                shutil.copy2(valid_paths[0], output_path)
            else:
                output_path.write_bytes(b"")

        # 探测时长
        duration_s = 0.0
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                duration_s = float(stdout.decode().strip())
        except Exception:
            pass

        return {"output_path": str(output_path), "duration_s": duration_s}

    @classmethod
    def init_from_config(cls, config_path: str | Path) -> Idea2VideoPipeline:
        """从 YAML 配置文件初始化管线。"""
        path = Path(config_path)
        if path.exists():
            config = Idea2VideoConfig.from_yaml(path)
        else:
            config = Idea2VideoConfig()

        return cls(config=config)
