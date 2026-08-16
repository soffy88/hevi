"""云渲染工作流 —— @remotion/lambda 接入(3O 内化 Round 3,补"云渲染"缺口)。

Remotion 生态的 @remotion/lambda 提供 AWS Lambda 渲染;hevi-remotion 未接入。
本 workflow 提供三件套包装:本地渲染(现有 remotion_render_workflow)→ 云端渲染
(remotion lambda deploy/render,需 AWS 配置)→ 优雅降级(未配置返回 failed 并给出
配置指引,不假装成功)。

3O 归属(待上游): `omodul.cloud_render_workflow`。
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CloudRenderConfig:
    """云渲染配置。"""

    project_dir: Path  # hevi-remotion 工程根
    composition_id: str
    out_path: Path
    region: str = "us-east-1"
    serve_url: str = ""  # 已部署的 serve url(空 = 自动 deploy)
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class CloudRenderInput:
    """云渲染输入。"""

    assets_dir: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _require_lambda(project_dir: Path) -> str:
    """确认 @remotion/lambda 已安装;缺返回提示。"""
    node_modules = project_dir / "node_modules" / "@remotion" / "lambda"
    if node_modules.exists():
        return ""
    return "hevi-remotion 未安装 @remotion/lambda(npm i @remotion/lambda @remotion/cli)"


async def cloud_render_workflow(
    config: CloudRenderConfig,
    input_data: CloudRenderInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:deploy(可选)→ render on Lambda → 下载成片。

    Returns:
        {"status": "completed"|"failed", "error": ...}。未配置 AWS/未装 lambda → failed
        带配置指引(不假装成功)。
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        missing = _require_lambda(config.project_dir)
        if missing:
            return {"status": "failed", "error": missing}
        if not config.project_dir.exists():
            return {"status": "failed", "error": f"project not found: {config.project_dir}"}
        _step("preflight", 10.0)

        cwd = str(config.project_dir)
        props_json = output_dir / "props.json"
        props_json.write_text(
            json.dumps(config.props, ensure_ascii=False), encoding="utf-8"
        )

        serve_url = config.serve_url
        if not serve_url:
            deploy = subprocess.run(
                ["npx", "remotion", "lambda", "deploy", "--region", config.region],
                capture_output=True, text=True, timeout=900, check=False, cwd=cwd,
            )
            if deploy.returncode != 0:
                return {
                    "status": "failed",
                    "error": (
                        f"remotion lambda deploy failed: {deploy.stderr[-400:]} "
                        "(需 AWS 凭证: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)"
                    ),
                }
            serve_url = deploy.stdout.strip().splitlines()[-1] if deploy.stdout.strip() else ""
        _step("deploy", 45.0)

        render = subprocess.run(
            [
                "npx", "remotion", "lambda", "render", config.composition_id,
                "--serve-url", serve_url, "--region", config.region,
                "--props", str(props_json), "--out", str(config.out_path),
            ],
            capture_output=True, text=True, timeout=1800, check=False, cwd=cwd,
        )
        if render.returncode != 0:
            return {
                "status": "failed",
                "error": f"remotion lambda render failed: {render.stderr[-400:]}",
            }
        _step("render", 90.0)

        report = {
            "status": "completed",
            "output_path": str(config.out_path),
            "serve_url": serve_url,
            "region": config.region,
        }
        report_path = output_dir / "cloud_render_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", **report, "report_path": str(report_path)}
    except Exception as e:
        logger.exception("cloud_render_workflow failed")
        return {"status": "failed", "error": str(e)}
