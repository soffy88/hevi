"""PR→视频工作流 —— GitHub PR → changelog/功能揭示解说(3O 内化 Round 3)。

来源: HyperFrames /pr-to-video。能力:PR(URL / owner#N / "this PR")→ gh CLI 读
diff/标题/描述 → changelog 化解说计划(文件列表 → 分段 → 每段一屏:标题+要点+
diff 高亮提示)。gh CLI 缺失/失败时降级为"手动粘贴 PR 信息"模式,不整链崩溃。

确定性部分(可测):PR 原始数据(标题/描述/diff 统计)→ changelog 分段 → 分镜计划。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PrVideoConfig:
    """PR→视频配置。"""

    out_path: Path
    pr_ref: str = ""  # "owner/repo#N" 或 URL;空 = 手动粘贴模式
    repo_dir: Path | None = None  # gh 在其中执行(可空)
    max_segments: int = 6  # 分段上限(控制成片长度)


@dataclass
class PrVideoInput:
    """输入:PR 原始数据(gh 拉不到时手动粘贴)。"""

    title: str = ""
    body: str = ""
    changed_files: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)  # {additions, deletions}
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PrSegment:
    """一段 changelog 解说。"""

    index: int
    title: str
    points: list[str]
    file_hint: str = ""


@dataclass
class PrVideoPlan:
    """PR→视频分镜计划。"""

    segments: list[PrSegment]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "segments": [
                {"index": s.index, "title": s.title, "points": s.points, "file_hint": s.file_hint}
                for s in self.segments
            ],
        }


def build_pr_segments(input_data: PrVideoInput, *, max_segments: int = 6) -> list[PrSegment]:
    """确定性:文件/描述 → 分段(按功能域聚,每段 = 一屏)。"""
    segments: list[PrSegment] = []
    if input_data.title:
        segments.append(
            PrSegment(
                index=1,
                title=input_data.title[:40],
                points=["PR 核心改动"],
                file_hint="",
            )
        )
    # 按顶层目录聚文件,取前 max_segments-1 组
    buckets: dict[str, list[str]] = {}
    for f in input_data.changed_files:
        top = f.split("/")[0] if "/" in f else "(root)"
        buckets.setdefault(top, []).append(f)
    for i, (top, files) in enumerate(sorted(buckets.items()), start=len(segments) + 1):
        if len(segments) >= max_segments:
            break
        segments.append(
            PrSegment(
                index=i,
                title=f"{top} 模块",
                points=[f.split("/")[-1] for f in files[:4]],
                file_hint=files[0],
            )
        )
    if not segments:
        segments.append(
            PrSegment(index=1, title=input_data.title or "PR 变更", points=["见 PR 描述"])
        )
    return segments


def _fetch_pr_via_gh(config: PrVideoConfig) -> PrVideoInput:
    """gh CLI 拉 PR 原始数据;缺 gh 或失败抛 RuntimeError(由调用方降级)。"""
    if not config.pr_ref or shutil.which("gh") is None:
        raise RuntimeError("gh CLI 不可用或无 pr_ref")
    ref = config.pr_ref.replace("https://github.com/", "")
    cwd = str(config.repo_dir) if config.repo_dir else None
    title = subprocess.run(
        [
            "gh", "pr", "view", ref, "--json",
            "title,body,additions,deletions,files",
            "--jq",
            "{title:.title, body:.body, additions:.additions, "
            "deletions:.deletions, files:[.files[].path]}",
        ],
        capture_output=True, text=True, timeout=60, check=False, cwd=cwd,
    )
    if title.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {title.stderr[-300:]}")
    data = json.loads(title.stdout)
    return PrVideoInput(
        title=data.get("title", ""),
        body=data.get("body", "") or "",
        changed_files=list(data.get("files", [])),
        stats={"additions": data.get("additions", 0), "deletions": data.get("deletions", 0)},
    )


async def pr_to_video_workflow(
    config: PrVideoConfig,
    input_data: PrVideoInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:gh 拉取(降级手动)→ 分段计划 → report。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        # gh 拉取;失败 → 用手动输入(空标题也允许,计划用占位)
        fetched = False
        if config.pr_ref and not input_data.title:
            try:
                input_data = _fetch_pr_via_gh(config)
                fetched = True
            except RuntimeError as e:
                logger.warning("pr_to_video: gh fetch failed, fallback manual: %s", e)
        _step("fetch", 35.0)

        segments = build_pr_segments(input_data, max_segments=config.max_segments)
        plan = PrVideoPlan(
            segments=segments,
            meta={
                "pr_ref": config.pr_ref,
                "fetched": fetched,
                "stats": input_data.stats,
            },
        )
        _step("plan", 70.0)

        report = {"status": "completed", "plan": plan.to_dict()}
        report_path = output_dir / "pr_video_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", "plan": plan.to_dict(), "report_path": str(report_path)}
    except Exception as e:
        logger.exception("pr_to_video_workflow failed")
        return {"status": "failed", "error": str(e)}
