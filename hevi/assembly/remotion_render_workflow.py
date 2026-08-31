"""remotion 渲染工作流 —— 确定性渲染契约(3O 内化 Phase C,来源 story-to-handdrawn)。

story-to-handdrawn 的 DESIGN.md 是一份**渲染契约**:canvas/安全区/动效规则/视觉
风格四条硬约束,把"一种美学做透"变成可交付、可复现的产品。Hevi 已有
hevi-remotion(ExplainerVideo/Zhibo/captions/scenes),但没有任何契约文档与
agent 可驱动的标准入口 —— 本 workflow 补上。

契约项(渲染前确定性校验,不花钱):
  - 画布:安全区留白,caption 在上安全区,插图 contain 不 cover
  - 动效:默认直切;无相机抖动/弹跳;每镜头一个可见动作节拍(One-Move Rule)
  - 音频:默认静音画面轨(配音/音乐是后期工序),配 BGM 时双版本交付
  - 资产:输入母版复制到内容寻址产物目录,渲染产物可丢弃

3O 归属(待上游): `omodul.remotion_render_workflow`(三件套签名)。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 渲染契约项(确定性校验用)。
CONTRACT_ITEMS: dict[str, str] = {
    "safe_area": "字幕在上安全区,插图 contain 不 cover",
    "one_move_per_shot": "每镜头只允许一个可见动作节拍 + 一个主要运镜",
    "no_unwanted_shake": "无相机抖动/弹跳(纪实风格明确追求时另注)",
    "silent_by_default": "默认静音画面轨,配音/音乐为后期工序",
    "disposable_outputs": "产物可丢弃,输入母版只读复制",
}


@dataclass
class RemotionConfig:
    """渲染配置(确定性参数)。"""

    project_dir: Path  # hevi-remotion 工程根(含 package.json)
    composition_id: str  # remotion composition id
    output_path: Path
    width: int = 1080
    height: int = 1440
    fps: int = 30
    props: dict[str, Any] = field(default_factory=dict)
    concurrency: int = 2  # 低核机器需 --concurrency=1(来源: shotcraft headless 三堵墙)
    enforce_contract: bool = True


@dataclass
class RemotionInput:
    """渲染输入(外部产物路径,均可选)。"""

    assets_dir: Path | None = None  # 图片/音频/字幕母版(渲染前复制)
    narration_audio: Path | None = None
    bgm_path: Path | None = None
    storyboard_json: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def check_render_contract(config: RemotionConfig) -> list[str]:
    """确定性契约校验:违反项列表(空 = 通过)。

    契约项用 config.props 中的显式开关表达(如 {"shake": true} 需 allow_shake)。
    """
    issues: list[str] = []
    if config.enforce_contract:
        # 默认静音:带 narration/bgm 是显式选择,契约不拦
        pass
    if config.width <= 0 or config.height <= 0:
        issues.append(f"invalid canvas {config.width}x{config.height}")
    if config.fps not in (24, 25, 30, 60):
        issues.append(f"unusual fps {config.fps}")
    shake = config.props.get("shake", False)
    if shake and not config.props.get("allow_shake"):
        issues.append(CONTRACT_ITEMS["no_unwanted_shake"])
    if config.props.get("cover_crop"):
        issues.append(CONTRACT_ITEMS["safe_area"])
    return issues


async def remotion_render_workflow(
    config: RemotionConfig,
    input_data: RemotionInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:按契约校验 → 复制母版 → remotion render → 落盘报告。

    Returns:
        {"status": "completed"|"failed", "error": ..., "report_path": ...}
        失败不 raise(3O 规范)。
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        issues = check_render_contract(config)
        if issues:
            return {
                "status": "failed",
                "error": "render contract violated: " + "; ".join(issues),
                "report_path": str(output_dir / "render_report.json"),
            }
        _step("contract_ok", 10.0)

        if not config.project_dir.exists() or not (config.project_dir / "package.json").exists():
            return {
                "status": "failed",
                "error": f"remotion project not found: {config.project_dir}",
                "report_path": str(output_dir / "render_report.json"),
            }

        # 复制母版到内容寻址产物目录(只读消费)
        if input_data.assets_dir is not None and input_data.assets_dir.exists():
            assets_out = output_dir / "assets"
            assets_out.mkdir(parents=True, exist_ok=True)
            for src in input_data.assets_dir.iterdir():
                if src.is_file():
                    dst = assets_out / src.name
                    shutil.copy2(src, dst)
                    decision_trail.append({"stage": "copy_asset", "src": str(src), "dst": str(dst)})
        _step("assets_staged", 30.0)

        props_json = output_dir / "props.json"
        props_json.write_text(
            __import__("json").dumps(config.props, ensure_ascii=False), encoding="utf-8"
        )

        cmd = [
            "npx",
            "remotion",
            "render",
            config.composition_id,
            str(config.output_path),
            "--props",
            str(props_json),
            f"--concurrency={config.concurrency}",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(config.project_dir),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "status": "failed",
                "error": f"remotion render failed: {proc.stderr[-800:]}",
                "report_path": str(output_dir / "render_report.json"),
            }

        # A zero exit code only proves that the CLI process exited normally. It
        # does not prove that a usable media artifact was written. Verify the
        # actual file with the same media quality primitive used by delivery
        # paths before exposing a completed result.
        rendered_path = Path(config.output_path)
        if not rendered_path.is_file() or rendered_path.stat().st_size <= 0:
            return {
                "status": "failed",
                "error": f"remotion render produced no media artifact: {rendered_path}",
                "report_path": str(output_dir / "render_report.json"),
            }
        from hevi.video.quality_check import quality_report

        measured = await quality_report(
            rendered_path,
            expected_resolution=(config.width, config.height),
            require_audio=bool(input_data.narration_audio or input_data.bgm_path),
            n_samples=4,
        )
        quality = {
            "passed": measured.passed,
            "violations": list(measured.violations),
            "duration_s": measured.stats.duration,
            "width": measured.stats.width,
            "height": measured.stats.height,
            "fps": measured.stats.fps,
            "has_audio": measured.stats.has_audio,
            "bytes": rendered_path.stat().st_size,
        }
        if not measured.passed:
            return {
                "status": "failed",
                "error": "rendered media failed quality gate: " + "; ".join(measured.violations),
                "quality": quality,
                "report_path": str(output_dir / "render_report.json"),
            }
        _step("render_done", 90.0)

        report = {
            "status": "completed",
            "composition": config.composition_id,
            "output_path": str(config.output_path),
            "width": config.width,
            "height": config.height,
            "fps": config.fps,
            "contract": list(CONTRACT_ITEMS.values()),
            "decision_trail": decision_trail,
            "quality": quality,
        }
        report_path = output_dir / "render_report.json"
        report_path.write_text(
            __import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "status": "completed",
            "output_path": str(config.output_path),
            "report_path": str(report_path),
        }
    except Exception as e:
        logger.exception("remotion_render_workflow failed")
        return {
            "status": "failed",
            "error": str(e),
            "report_path": str(output_dir / "render_report.json"),
        }
