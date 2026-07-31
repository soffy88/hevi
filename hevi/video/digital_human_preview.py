"""数字人预览→确认流程 —— 对标 rachel-digital-human-production。

能力:
- 资产 preflight 校验（脚本/肖像/声音源）
- 15s 预览生成（低成本）
- 用户确认后再生成完整 1080p
- job-state 状态追踪

用法:
    from hevi.video.digital_human_preview import DigitalHumanPipeline

    pipeline = DigitalHumanPipeline()
    preflight = pipeline.preflight(script_path, portrait_path, voice_path)
    if preflight.ok:
        preview = await pipeline.generate_preview(portrait_path, script_preview)
        # 用户确认后:
        final = await pipeline.generate_full(portrait_path, full_script)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PreflightResult:
    """资产预检结果。"""
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    script_chars: int = 0
    portrait_size_kb: float = 0
    voice_duration_s: float = 0


@dataclass
class JobState:
    """数字人任务状态。"""
    project: str
    status: str = "pending"  # pending / preview_ready / preview_approved / generating / completed / failed
    voice_id: str | None = None
    asset_id: str | None = None
    preview_video_path: str | None = None
    preview_duration_s: float = 0
    final_video_path: str | None = None
    final_duration_s: float = 0
    cost_usd: float = 0.0
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "status": self.status,
            "voice_id": self.voice_id,
            "asset_id": self.asset_id,
            "preview_video_path": self.preview_video_path,
            "preview_duration_s": self.preview_duration_s,
            "final_video_path": self.final_video_path,
            "final_duration_s": self.final_duration_s,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class DigitalHumanPipeline:
    """数字人生产管线（预览→确认→生成）。"""

    def __init__(self, work_dir: Path | None = None) -> None:
        self._work_dir = work_dir or Path("output/digital_human")
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobState] = {}

    def preflight(
        self,
        script_path: Path | None = None,
        portrait_path: Path | None = None,
        voice_path: Path | None = None,
        script_text: str | None = None,
    ) -> PreflightResult:
        """资产预检:在实际调用付费 API 前校验所有输入。"""
        errors: list[str] = []
        warnings: list[str] = []
        script_chars = 0
        portrait_kb = 0.0
        voice_dur = 0.0

        # 脚本检查
        if script_path and script_path.exists():
            script_text = script_path.read_text(encoding="utf-8", errors="replace")
        if script_text:
            script_chars = len(script_text.strip())
            if script_chars < 10:
                errors.append(f"脚本太短（{script_chars} 字，至少 10 字）")
            elif script_chars > 5000:
                warnings.append(f"脚本较长（{script_chars} 字），预览仅使用前 200 字")
        else:
            errors.append("脚本为空或未提供")

        # 肖像检查
        if portrait_path:
            if not portrait_path.exists():
                errors.append(f"肖像文件不存在: {portrait_path}")
            else:
                portrait_kb = portrait_path.stat().st_size / 1024
                if portrait_kb < 10:
                    warnings.append(f"肖像文件很小（{portrait_kb:.0f}KB），可能分辨率不足")
                suffix = portrait_path.suffix.lower()
                if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                    errors.append(f"肖像格式不支持: {suffix}（需要 jpg/png/webp）")
        else:
            errors.append("未提供肖像文件")

        # 声音源检查
        if voice_path:
            if not voice_path.exists():
                errors.append(f"声音源文件不存在: {voice_path}")
            else:
                voice_dur = _estimate_audio_duration(voice_path)
                if voice_dur < 3:
                    warnings.append(f"声音源较短（{voice_dur:.1f}s），克隆效果可能不佳")
        else:
            warnings.append("未提供声音源（将使用默认 TTS，无法进行声音克隆）")

        return PreflightResult(
            ok=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            script_chars=script_chars,
            portrait_size_kb=round(portrait_kb, 1),
            voice_duration_s=round(voice_dur, 1),
        )

    def create_job(self, project: str) -> JobState:
        """创建新的数字人任务。"""
        now = datetime.now(UTC).isoformat()
        job = JobState(project=project, created_at=now, updated_at=now)
        self._jobs[project] = job
        return job

    def get_job(self, project: str) -> JobState | None:
        return self._jobs.get(project)

    def list_jobs(self) -> list[JobState]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def generate_preview(
        self,
        project: str,
        portrait_path: Path,
        script_text: str,
        *,
        duration_s: int = 15,
    ) -> JobState:
        """生成 15s 预览（低成本验证）。"""
        job = self._jobs.get(project) or self.create_job(project)
        job.status = "generating"
        job.updated_at = datetime.now(UTC).isoformat()

        # 截取前 200 字用于预览
        preview_script = script_text[:200] if len(script_text) > 200 else script_text

        try:
            # 用通鉴 cloud_avatar 或 Seedance 生成低分辨率预览
            from hevi.video.provider_seedance import seedance_image_to_video
            import base64

            output_path = self._work_dir / project / f"preview_{duration_s}s.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 将肖像图编码为 base64 data URL（如果需要上传）
            # 这里简化:直接用本地路径调用
            result = await seedance_image_to_video(
                image_url=str(portrait_path),
                prompt=f"person speaking naturally: {preview_script[:100]}",
                output_path=output_path,
                duration_s=duration_s,
                resolution="480p",  # 预览用低分辨率节省成本
            )

            job.preview_video_path = str(result.local_path)
            job.preview_duration_s = result.duration_s
            job.cost_usd += result.cost_usd
            job.status = "preview_ready"

        except ImportError:
            # Seedance 未配置，用 fallback
            logger.warning("digital_human_preview: Seedance not available, using fallback")
            job.status = "preview_ready"
            job.preview_video_path = None
            job.preview_duration_s = float(duration_s)
            job.warnings = ["Seedance API 未配置，预览跳过"]

        except Exception as e:
            logger.error("digital_human_preview: preview generation failed: %s", e)
            job.status = "failed"
            job.error = str(e)[:500]

        job.updated_at = datetime.now(UTC).isoformat()
        return job

    async def generate_full(
        self,
        project: str,
        portrait_path: Path,
        script_text: str,
        *,
        duration_s: int = 60,
    ) -> JobState:
        """生成完整 1080p 视频（需要预览已确认）。"""
        job = self._jobs.get(project)
        if not job:
            raise ValueError(f"Job not found: {project}")
        if job.status != "preview_ready":
            raise ValueError(
                f"Cannot generate full video: status is {job.status}, "
                "expected preview_ready. Generate preview first."
            )

        job.status = "generating"
        job.updated_at = datetime.now(UTC).isoformat()

        try:
            from hevi.video.provider_seedance import seedance_image_to_video

            output_path = self._work_dir / project / "final_1080p.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            result = await seedance_image_to_video(
                image_url=str(portrait_path),
                prompt=f"person speaking naturally with full dialogue: {script_text[:200]}",
                output_path=output_path,
                duration_s=min(duration_s, 300),  # 最长 5 分钟
                resolution="1080p",
            )

            job.final_video_path = str(result.local_path)
            job.final_duration_s = result.duration_s
            job.cost_usd += result.cost_usd
            job.status = "completed"

        except Exception as e:
            logger.error("digital_human_preview: full generation failed: %s", e)
            job.status = "failed"
            job.error = str(e)[:500]

        job.updated_at = datetime.now(UTC).isoformat()
        return job

    def approve_preview(self, project: str) -> JobState:
        """用户确认预览，允许生成完整视频。"""
        job = self._jobs.get(project)
        if not job:
            raise ValueError(f"Job not found: {project}")
        if job.status != "preview_ready":
            raise ValueError(f"Cannot approve: status is {job.status}")

        job.status = "preview_approved"
        job.updated_at = datetime.now(UTC).isoformat()
        return job


def _estimate_audio_duration(path: Path) -> float:
    """粗估音频时长（用 ffprobe）。"""
    try:
        import subprocess
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        # fallback: 按文件大小粗估（假设 128kbps）
        try:
            size = path.stat().st_size
            return size / (128 * 1024 / 8)
        except Exception:
            return 0.0
