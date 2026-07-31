"""Novel2Video Pipeline — 长文本→视频（对标 ViMax novel2video_pipeline.py）。

处理小说、文章、报告等长文本，将其转换为视频：
  1. compress_narrative() — 叙事压缩（5000字→5-8个视觉节拍）
  2. extract_events() — 事件提取（从压缩叙事中提取关键事件）
  3. split_scenes() — 场景拆分（每个事件→1-3个场景）
  4. generate_video() — 调用 Idea2Video 生成最终视频

支持：
  - 章节分割（按段落/标题/分隔符）
  - 角色追踪（跨章节身份一致性）
  - 叙事压缩（保留关键情节，删除冗余描述）
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from hevi.agent_runtime.checkpoint import PipelineCheckpoint
from hevi.director.idea2video import Idea2VideoConfig, Idea2VideoPipeline, Idea2VideoResult


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class NarrativeBeat:
    """叙事节拍（压缩后的关键情节）。"""

    beat_id: int
    title: str
    description: str
    characters: list[str] = field(default_factory=list)
    location: str = ""
    emotion: str = ""
    duration_s: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "title": self.title,
            "description": self.description,
            "characters": self.characters,
            "location": self.location,
            "emotion": self.emotion,
            "duration_s": self.duration_s,
        }


@dataclass
class Event:
    """事件（从叙事中提取的关键动作）。"""

    event_id: int
    description: str
    characters: list[str] = field(default_factory=list)
    location: str = ""
    time: str = ""
    beats: list[NarrativeBeat] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "description": self.description,
            "characters": self.characters,
            "location": self.location,
            "time": self.time,
            "beats": [b.to_dict() for b in self.beats],
        }


@dataclass
class Chapter:
    """章节（长文本的分段单元）。"""

    chapter_id: int
    title: str
    content: str
    word_count: int = 0

    def __post_init__(self):
        if self.word_count == 0:
            self.word_count = len(self.content)


@dataclass
class Novel2VideoConfig:
    """Novel2Video 配置。"""

    working_dir: Path = field(default_factory=lambda: Path(".working_dir/novel2video"))
    max_beats_per_chapter: int = 8
    max_events: int = 20
    max_scenes: int = 30
    chapter_split_pattern: str = r"\n\n(?=[A-Z\u4e00-\u9fff])"  # 段落分隔
    target_duration_s: float = 120.0  # 目标总时长
    fps: int = 24
    resolution: str = "720p"

    def to_dict(self) -> dict[str, Any]:
        return {
            "working_dir": str(self.working_dir),
            "max_beats_per_chapter": self.max_beats_per_chapter,
            "max_events": self.max_events,
            "max_scenes": self.max_scenes,
            "chapter_split_pattern": self.chapter_split_pattern,
            "target_duration_s": self.target_duration_s,
            "fps": self.fps,
            "resolution": self.resolution,
        }


@dataclass
class Novel2VideoResult:
    """Novel2Video 结果。"""

    final_video_path: Path
    original_text: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    compressed_narrative: str = ""
    events: list[Event] = field(default_factory=list)
    duration_s: float = 0.0
    character_registry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_video_path": str(self.final_video_path),
            "original_text": self.original_text[:500],  # 截断
            "chapter_count": len(self.chapters),
            "event_count": len(self.events),
            "duration_s": self.duration_s,
        }


# ── 管线实现 ──────────────────────────────────────────────────────────


class Novel2VideoPipeline:
    """长文本→视频管线。

    用法：
        pipeline = Novel2VideoPipeline(config=Novel2VideoConfig(), llm_caller=my_llm)
        result = await pipeline.run(novel_text)
    """

    def __init__(
        self,
        config: Optional[Novel2VideoConfig] = None,
        llm_caller: Optional[Callable] = None,
        idea2video_pipeline: Optional[Idea2VideoPipeline] = None,
    ):
        self.config = config or Novel2VideoConfig()
        self.llm_caller = llm_caller
        self.checkpoint = PipelineCheckpoint(self.config.working_dir)
        self.idea2video = idea2video_pipeline or Idea2VideoPipeline(
            config=Idea2VideoConfig(
                working_dir=self.config.working_dir / "idea2video",
                max_scenes=self.config.max_scenes,
                fps=self.config.fps,
                resolution=self.config.resolution,
            ),
            llm_caller=llm_caller,
        )

    async def run(self, novel_text: str, user_requirement: str = "") -> Novel2VideoResult:
        """运行完整管线。

        Args:
            novel_text: 长文本（小说/文章/报告）
            user_requirement: 用户额外要求

        Returns:
            Novel2VideoResult
        """
        result = Novel2VideoResult(
            final_video_path=self.config.working_dir / "final_video.mp4",
            original_text=novel_text,
        )

        # 阶段 1: 章节分割
        chapter_stage = self.checkpoint.stage("split_chapters")
        chapters_data = await self.checkpoint.run_if_missing(
            chapter_stage,
            "main",
            lambda: self._split_chapters(novel_text),
        )
        result.chapters = chapters_data["chapters"]

        # 阶段 2: 叙事压缩（每章独立压缩）
        compress_stage = self.checkpoint.stage("compress_narrative")
        compressed_data = await self.checkpoint.run_if_missing(
            compress_stage,
            "main",
            lambda: self._compress_narrative(result.chapters),
        )
        result.compressed_narrative = compressed_data["compressed_text"]

        # 阶段 3: 事件提取
        events_stage = self.checkpoint.stage("extract_events")
        events_data = await self.checkpoint.run_if_missing(
            events_stage,
            "main",
            lambda: self._extract_events(result.compressed_narrative),
        )
        result.events = events_data["events"]

        # 阶段 4: 生成视频（将事件转换为 idea，调用 Idea2Video）
        idea = self._events_to_idea(result.events, user_requirement)
        idea_result = await self.idea2video.run(idea, user_requirement)

        result.final_video_path = idea_result.final_video_path
        result.duration_s = idea_result.duration_s
        result.character_registry = idea_result.portrait_registry

        return result

    async def _split_chapters(self, text: str) -> dict[str, Any]:
        """阶段 1: 章节分割。"""
        # 尝试按标题分割（## 标题 或 第X章）
        title_pattern = r"(?:^|\n)(?:#+\s+.+|第[一二三四五六七八九十\d]+章[^\n]*)"
        parts = re.split(title_pattern, text)
        titles = re.findall(title_pattern, text)

        chapters: list[Chapter] = []
        for i, (title, content) in enumerate(zip(titles, parts[1:]), 1):
            chapters.append(Chapter(
                chapter_id=i,
                title=title.strip(),
                content=content.strip(),
            ))

        # 如果没有标题，按段落分割
        if not chapters:
            parts = re.split(self.config.chapter_split_pattern, text)
            for i, part in enumerate(parts, 1):
                if len(part.strip()) > 100:  # 过滤空段落
                    chapters.append(Chapter(
                        chapter_id=i,
                        title=f"Chapter {i}",
                        content=part.strip(),
                    ))

        return {"chapters": chapters}

    async def _compress_narrative(self, chapters: list[Chapter]) -> dict[str, Any]:
        """阶段 2: 叙事压缩。"""
        compressed_parts: list[str] = []

        for chapter in chapters:
            prompt = f"""将以下章节压缩为 5-8 个关键视觉节拍（narrative beats）。

章节标题：{chapter.title}
章节内容：
{chapter.content}

要求：
1. 保留关键情节和角色动作
2. 删除冗余描述和对话细节
3. 每个节拍包含：标题、描述、涉及角色、地点、情感基调
4. 输出格式：每个节拍一行，格式为 "标题 | 描述 | 角色 | 地点 | 情感"

示例：
相遇 | 小明在咖啡馆遇到小红 | 小明,小红 | 咖啡馆 | 惊喜
争吵 | 两人因误会发生争执 | 小明,小红 | 街道 | 愤怒
和好 | 小明道歉，两人重归于好 | 小明,小红 | 公园 | 温馨
"""
            if self.llm_caller:
                compressed = await self.llm_caller(prompt)
                compressed_parts.append(f"## {chapter.title}\n{compressed}")
            else:
                # 无 LLM：简单截取前 500 字
                truncated = chapter.content[:500]
                compressed_parts.append(f"## {chapter.title}\n{truncated}")

        return {"compressed_text": "\n\n".join(compressed_parts)}

    async def _extract_events(self, compressed_narrative: str) -> dict[str, Any]:
        """阶段 3: 事件提取。"""
        prompt = f"""从以下压缩叙事中提取关键事件（最多 {self.config.max_events} 个）。

压缩叙事：
{compressed_narrative}

要求：
1. 每个事件包含：描述、涉及角色、地点、时间
2. 事件按时间顺序排列
3. 输出 JSON 格式：
{{
  "events": [
    {{
      "description": "事件描述",
      "characters": ["角色1", "角色2"],
      "location": "地点",
      "time": "时间"
    }}
  ]
}}
"""
        if self.llm_caller:
            from hevi.utils.robust_json import robust_json_loads
            raw = await self.llm_caller(prompt)
            data = robust_json_loads(raw)
            events_data = data.get("events", [])
        else:
            # 无 LLM：从文本中提取简单事件
            lines = compressed_narrative.split("\n")
            events_data = []
            for i, line in enumerate(lines[:self.config.max_events], 1):
                if "|" in line:
                    parts = line.split("|")
                    events_data.append({
                        "description": parts[1].strip() if len(parts) > 1 else line,
                        "characters": [c.strip() for c in parts[2].split(",")] if len(parts) > 2 else [],
                        "location": parts[3].strip() if len(parts) > 3 else "",
                        "time": "",
                    })

        events: list[Event] = []
        for i, e in enumerate(events_data, 1):
            events.append(Event(
                event_id=i,
                description=e.get("description", ""),
                characters=e.get("characters", []),
                location=e.get("location", ""),
                time=e.get("time", ""),
            ))

        return {"events": events}

    def _events_to_idea(self, events: list[Event], user_requirement: str) -> str:
        """将事件列表转换为 Idea2Video 的 idea 输入。"""
        event_summaries = []
        for e in events:
            chars = ", ".join(e.characters) if e.characters else "某人"
            location = f"在{e.location}" if e.location else ""
            event_summaries.append(f"- {chars}{location}：{e.description}")

        idea = "故事包含以下关键事件：\n" + "\n".join(event_summaries)

        if user_requirement:
            idea += f"\n\n额外要求：{user_requirement}"

        return idea

    @classmethod
    def init_from_config(cls, config_path: str | Path) -> "Novel2VideoPipeline":
        """从配置文件初始化。"""
        import yaml
        with open(config_path) as f:
            data = yaml.safe_load(f)

        config = Novel2VideoConfig(
            working_dir=Path(data.get("working_dir", ".working_dir/novel2video")),
            max_beats_per_chapter=data.get("max_beats_per_chapter", 8),
            max_events=data.get("max_events", 20),
            max_scenes=data.get("max_scenes", 30),
            target_duration_s=data.get("target_duration_s", 120.0),
        )
        return cls(config=config)
