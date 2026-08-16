"""资产包导出工作流 —— mp4 + 完整制作包交付(3O 内化 Round 3d,来源 dramaclaw export)。

dramaclaw 的 build_episode_zip_file:一集成片 = SRT + 视频 + 资产包打成 zip 交付。
这正对应 HEVI-ARCH §6.4:专业/代理商用户拿 mp4 + **完整制作包**(镜头清单、连续性报告、
StylePack 引用说明)—— 撑起新定价层级,零增量计算成本。

本模块为 hevi 暂驻(待上游 `omodul.export_pack_workflow`):
  - 确定性 manifest 构建(镜头清单/字幕/评分/连续性/引用)
  - zip 打包(纯文件 IO 可测);缺项记 None 不阻断(三件套纪律)。
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExportPackConfig:
    """导出配置。"""

    out_dir: Path  # 成片产物目录(video/srt/shots/verdicts 等)
    project_name: str
    episode_no: int
    zip_path: Path


@dataclass
class ExportPackInput:
    """输入:可选各产物路径。"""

    video: Path | None = None
    srt: Path | None = None
    shot_list: Path | None = None  # 镜头清单 JSON
    continuity_report: Path | None = None  # 连续性报告 JSON
    stylepack_ref: str = ""  # StylePack 引用说明文本
    shot_verdicts: Path | None = None  # shot_verdict 导出 JSON
    extra_files: dict[str, Path] = field(default_factory=dict)  # 附加 {arc_name: path}


@dataclass
class ExportManifest:
    """制作包清单(面向客户的交付目录)。"""

    project_name: str
    episode_no: int
    entries: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "episode_no": self.episode_no,
            "entries": self.entries,
            "missing": self.missing,
        }


def build_export_manifest(config: ExportPackConfig, input_data: ExportPackInput) -> ExportManifest:
    """确定性 manifest:按固定顺序收集产物,缺项记 missing。"""
    manifest = ExportManifest(project_name=config.project_name, episode_no=config.episode_no)
    candidates: list[tuple[str, Path | None, str]] = [
        ("video.mp4", input_data.video, "成片视频"),
        ("subtitles.srt", input_data.srt, "字幕(SRT)"),
        ("shot_list.json", input_data.shot_list, "镜头清单"),
        ("continuity_report.json", input_data.continuity_report, "连续性报告"),
        ("shot_verdicts.json", input_data.shot_verdicts, "逐镜头评分"),
    ]
    for arc_name, path, label in candidates:
        if path is not None and path.exists():
            manifest.entries.append(
                {"arc": arc_name, "path": str(path), "label": label}
            )
        else:
            manifest.missing.append(f"{arc_name}({label})")
    for arc_name, path in sorted(input_data.extra_files.items()):
        if path.exists():
            manifest.entries.append({"arc": arc_name, "path": str(path), "label": arc_name})
        else:
            manifest.missing.append(f"{arc_name}(附加文件缺失)")
    return manifest


def write_manifest(manifest: ExportManifest, out_path: Path) -> Path:
    """manifest 落盘 JSON。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path


def build_zip(manifest: ExportManifest, zip_path: Path) -> Path:
    """按 manifest 打包 zip(缺项跳过,不阻断)。"""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in manifest.entries:
            p = Path(entry["path"])
            if p.exists():
                zf.write(p, arcname=entry["arc"])
        zf.writestr("manifest.json", json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
    return zip_path


async def export_pack_workflow(
    config: ExportPackConfig,
    input_data: ExportPackInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:manifest → zip → report。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        manifest = build_export_manifest(config, input_data)
        _step("manifest", 40.0)
        manifest_path = write_manifest(manifest, output_dir / "manifest.json")
        zip_path = build_zip(manifest, config.zip_path) if manifest.entries else None
        _step("pack", 85.0)

        report = {
            "status": "completed",
            "zip_path": str(zip_path) if zip_path else None,
            "manifest_path": str(manifest_path),
            "entries": len(manifest.entries),
            "missing": manifest.missing,
        }
        report_path = output_dir / "export_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", **report, "report_path": str(report_path)}
    except Exception as e:
        logger.exception("export_pack_workflow failed")
        return {"status": "failed", "error": str(e)}
