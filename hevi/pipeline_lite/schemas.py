"""v9.1 Lite 管道:数据契约(schemas)。

Lite 管道 = HTML + Playwright 无头录屏 + FFmpeg 混流,零 GPU、零云端视频 API,
一条极轻量的解说视频生产线。数据契约在这里定义,oprim/omodul/oapp 三方
都只引用本模块,杜绝面条代码里的隐式 dict 传参。

完整闭环(html-video × hevi):
  topic → LLM 出文案 → veya-loop 审稿 → 人确认 → 本地零费用出片。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

LitePipelineType = Literal["lite_html"]

LiteRunStatus = Literal[
    "drafting",
    "reviewing",
    "awaiting_confirm",
    "rendering",
    "completed",
    "failed",
]


class LiteCue(BaseModel):
    """一条 Lite 镜头:HTML 卡片的一段 + 对应的旁白文本。"""

    index: int = Field(ge=0)
    narration: str = Field(min_length=1, max_length=2000)
    template: str = Field(default="card", description="HTML 模板名(见 templates/)")
    props: dict[str, Any] = Field(default_factory=dict)


class LiteTaskContext(BaseModel):
    """工单上下文:装配全程传递,承载 Workspace 与产物路径。"""

    task_id: str = Field(min_length=1)
    topic: str = Field(min_length=1, max_length=500)
    cues: list[LiteCue] = Field(default_factory=list)
    voice: str = Field(default="edge_tts_zh")
    width: int = Field(default=720)
    height: int = Field(default=1280)
    fps: int = Field(default=24)
    output_name: str = Field(default="final.mp4")

    # 运行期产物路径(由 omodul 填充,不走隐式全局变量)。
    workspace_root: Path | None = None
    html_path: Path | None = None
    screen_capture_path: Path | None = None
    audio_path: Path | None = None
    final_path: Path | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.cues:
            raise ValueError("LiteTaskContext.cues 不能为空")

    @property
    def pipeline_type(self) -> str:
        return "lite_html"


class LiteAssembleResult(BaseModel):
    """装配结果:任务状态 + 产物路径 + 决策轨迹。"""

    task_id: str
    status: Literal["pending", "completed", "failed"] = "completed"
    video_path: Path | None = None
    error: str | None = None
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)
    progress: int = 100


class ScriptIssue(BaseModel):
    """veya-loop 单条质检问题。"""

    code: str
    message: str
    severity: Literal["hard", "soft"] = "soft"
    cue_index: int | None = None
    fix_hint: str = ""


class ScriptVerdict(BaseModel):
    """一轮文案质量裁决。"""

    passed: bool
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    issues: list[ScriptIssue] = Field(default_factory=list)
    summary: str = ""
    round: int = 0
    source: Literal["deterministic", "llm", "hybrid"] = "deterministic"


class ScriptDraft(BaseModel):
    """选题 → 文案草稿(含 hook / 标题 / cues)。"""

    topic: str
    title: str = ""
    hook: str = ""
    cues: list[LiteCue] = Field(default_factory=list)
    target_cues: int = Field(default=5, ge=3, le=12)
    language: str = "zh"


class VeyaLoopResult(BaseModel):
    """veya-loop 终态:审过的文案 + 每一轮裁决轨迹。"""

    draft: ScriptDraft
    passed: bool
    rounds: int = 0
    verdicts: list[ScriptVerdict] = Field(default_factory=list)
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)


class LiteRunRecord(BaseModel):
    """选题→审稿→确认→出片 的完整 run 状态(内存 + 磁盘落盘)。"""

    run_id: str
    status: LiteRunStatus = "drafting"
    topic: str
    draft: ScriptDraft | None = None
    loop: VeyaLoopResult | None = None
    task_id: str | None = None
    video_path: str | None = None
    preview_html_path: str | None = None  # 审稿 HTML(不落 MP4)
    error: str | None = None
    progress: int = 0
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)
    width: int = 720
    height: int = 1280
    fps: int = 24


__all__ = [
    "LiteAssembleResult",
    "LiteCue",
    "LiteRunRecord",
    "LiteRunStatus",
    "LiteTaskContext",
    "ScriptDraft",
    "ScriptIssue",
    "ScriptVerdict",
    "VeyaLoopResult",
]
