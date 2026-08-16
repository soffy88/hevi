"""RIFE 插帧 —— 引擎按环境自动选:ComfyUI VFI(comfy_vfi) > VapourSynth 方案 B(vspipe)
> Flowframes CLI。

hevi 约定:先超分、后插帧,顺序不可反;只处理画面,音频由 pipeline 从 raw 原轨回混。

引擎说明:
  - comfy_vfi(默认,本机优先):ComfyUI 核心 `FrameInterpolationModelLoader` +
    `FrameInterpolate`(ComfyUI ≥0.31 自带,模型放 models/frame_interpolation/,如
    rife49.pth)。零新依赖,走现有 ComfyUI 的 torch/CUDA,与 h3_local 同队列纪律。
  - vspipe(方案 B):VapourSynth + RIFE 插件(core.rife.RIFE),脚本模板可配。
  - flowframes:Flowframes CLI(Windows 工具,经 POST_FLOWFRAMES_EXE 指定)。

所有引擎缺失时抛 RifeUnavailable,pipeline 标记 no_interp 降级交付 —— 绝不假装成功。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 模板目录(与 flashvsr 共用 hevi/post/workflows/)。
_WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"
#: ComfyUI VFI 工作流模板(占位符约定同 h3 模板)。
_VFI_WORKFLOW = "rife_vfi_2x.json"
#: 需要核对的节点类(comfy_vfi 引擎)。
_VFI_NODE_CLASSES = (
    "VHS_LoadVideoPath",
    "FrameInterpolationModelLoader",
    "FrameInterpolate",
    "VHS_VideoCombine",
)

#: VapourSynth 脚本模板。%% 占位符由 build_vpy 替换。
#: 输入源:ffms2 优先,LSMASHSource 兜底;RIFE 调用按 rife_call 配置展开。
_VPY_TEMPLATE = """\
import vapoursynth as vs
core = vs.core
src = None
try:
    src = core.ffms2.Source(r"%%INPUT%%")
except Exception:
    src = core.lsmas.LWLibavSource(r"%%INPUT%%")
if src is None:
    raise RuntimeError("no usable source filter (ffms2 / lsmash)")
# 插帧前统一到 RGB 半精度(RIFE 推荐,省显存)
if src.format.color_family != vs.RGB:
    src = core.resize.Bicubic(src, format=vs.RGBH)
src = core.rife.RIFE(src, %%RIFE_KWARGS%%)
# 输出回 YUV 4:2:0 8bit 给编码器
out = core.resize.Bicubic(src, format=vs.YUV420P8, matrix_s="709")
out.set_output()
"""

_DEFAULT_RIFE_KWARGS: dict[str, Any] = {
    "model": "4.25",
    "factor_num": 2,
    "factor_den": 1,
    "sc": True,
}


class RifeUnavailable(Exception):
    """RIFE 不可用(vspipe/插件缺失或执行失败)。调用方标记 no_interp 降级。"""


def build_vpy(*, input_path: Path, rife_kwargs: dict[str, Any] | None = None) -> str:
    """渲染 .vpy 脚本内容。rife_kwargs 覆盖默认(model/factor_num/sc…),
    不同 RIFE 插件版本参数名不同(如 multi=2),由配置给出。"""
    kwargs = dict(_DEFAULT_RIFE_KWARGS)
    kwargs.update(rife_kwargs or {})
    rendered = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    return _VPY_TEMPLATE.replace("%%INPUT%%", str(input_path)).replace(
        "%%RIFE_KWARGS%%", rendered
    )


async def has_audio(path: Path) -> bool:
    """ffprobe 探测是否有音轨(供 pipeline 决定是否回混 H3 原音)。失败 → False。"""
    try:
        import json

        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        streams = json.loads(out or b"{}").get("streams", [])
        return any(s.get("codec_type") == "audio" for s in streams)
    except Exception:
        return False


async def _run_vspipe(
    script: Path, output_path: Path, *, timeout_s: float, y4m_pipe: bool = True
) -> Path:
    """vspipe -c y4m → ffmpeg 编码(硬编码 libx264 crf 16,与成片导出档一致)。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "vspipe",
        "-c",
        "y4m",
        "--progress",
        str(script),
        "-",
    ]
    ff_args = [
        "ffmpeg",
        "-y",
        "-f",
        "y4m",
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-crf",
        "16",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    ff = await asyncio.create_subprocess_exec(
        *ff_args,
        stdin=asyncio.subprocess.PIPE,  # 显式管道,由下方 _pump 转发 vspipe stdout
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        # asyncio StreamReader 不能直接作 subprocess stdin(无 fileno);
        # 手动泵送 vspipe y4m 流 → ffmpeg stdin,任一端退出即结束转发。
        async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    chunk = await src.read(64 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
            finally:
                dst.close()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await dst.wait_closed()

        await asyncio.wait_for(
            asyncio.gather(
                proc.wait(),
                ff.wait(),
                _pump(proc.stdout, ff.stdin),  # type: ignore[arg-type]  # PIPE 下两者必非 None
            ),
            timeout=timeout_s,
        )
    except TimeoutError:
        proc.kill()
        ff.kill()
        raise RifeUnavailable(f"vspipe 插帧超时({timeout_s:.0f}s): {output_path.name}") from None
    if proc.returncode != 0 or ff.returncode != 0:
        raise RifeUnavailable(
            f"vspipe 插帧失败(vspipe={proc.returncode}, ffmpeg={ff.returncode})"
        )
    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RifeUnavailable(f"vspipe 插帧产物缺失: {output_path}")
    return output_path


async def _run_flowframes(
    input_path: Path, output_path: Path, *, exe: str, multiplier: int, timeout_s: float
) -> Path:
    """Flowframes CLI(备选)。exe 由 POST_FLOWFRAMES_EXE / config 给。"""
    proc = await asyncio.create_subprocess_exec(
        exe,
        "--in",
        str(input_path),
        "--out",
        str(output_path),
        "--interp",
        f"rife{multiplier}x",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        raise RifeUnavailable(f"Flowframes 插帧超时({timeout_s:.0f}s)") from None
    if proc.returncode != 0:
        raise RifeUnavailable(f"Flowframes 退出码 {proc.returncode}")
    return output_path


def _model_options(info: dict[str, Any]) -> list[str]:
    """从 object_info 里抠出 frame_interpolation 模型列表(COMBO spec 结构)。"""
    spec = (
        info.get("FrameInterpolationModelLoader", {})
        .get("input", {})
        .get("required", {})
        .get("model_name")
    )
    if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict):
        return list(spec[1].get("options", []) or [])
    return []


async def _run_comfy_vfi(
    input_path: Path,
    output_path: Path,
    *,
    model: str,
    multiplier: int,
    fps: int,
    client: Any = None,
    timeout_s: float = 900.0,
) -> Path:
    """ComfyUI 核心 VFI:FrameInterpolationModelLoader + FrameInterpolate(multiplier)。

    与 h3_local 共用 ComfyClient(串行队列);模型文件必须在
    ComfyUI/models/frame_interpolation/ 下(如 rife49.pth)。
    """
    import httpx

    from hevi.providers.h3_local.comfy_client import ComfyClient, H3ComfyError

    client = client or ComfyClient(timeout_s=timeout_s)
    # 核对节点与模型都在(缺任一 → 明确不可用,不猜)
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{client.base_url}/object_info")
            r.raise_for_status()
            info = r.json()
        missing = [k for k in _VFI_NODE_CLASSES if k not in info]
        if missing:
            raise RifeUnavailable(
                "ComfyUI VFI 节点缺失: " + ", ".join(missing)
                + "(ComfyUI ≥0.31 自带;升级或改 POST_RIFE_ENGINE=vspipe)"
            )
        options = _model_options(info)
        if model not in options:
            raise RifeUnavailable(
                f"frame_interpolation 目录没有 {model!r}(现有: {options[:5]});"
                "下载 rife49.pth 放入 ComfyUI/models/frame_interpolation/"
            )
    except RifeUnavailable:
        raise
    except Exception as e:
        raise RifeUnavailable(f"ComfyUI 不可达({client.base_url}): {e}") from e

    workflow = client.build_workflow(
        _VFI_WORKFLOW,
        output_prefix=f"h3_rife_{output_path.stem[:32]}",
        extra_fills={
            "__VIDEO_PATH__": str(input_path.resolve()),
            "__RIFE_MODEL__": model,
            "__MULTIPLIER__": int(multiplier),
            "__FPS__": float(fps * multiplier),
        },
        workflows_dir=_WORKFLOWS_DIR,
    )
    try:
        return await client.run_workflow(  # type: ignore[no-any-return]
            workflow, output_path=output_path, timeout_s=timeout_s
        )
    except H3ComfyError as e:
        raise RifeUnavailable(f"ComfyUI VFI 执行失败: {e}") from e


async def _resolve_engine(cfg: dict[str, Any]) -> str:
    """引擎选择:显式配置 > 环境变量 > auto(comfy_vfi 优先,其次 vspipe,再 flowframes)。"""
    explicit = cfg.get("engine") or os.getenv("POST_RIFE_ENGINE")
    if explicit and explicit != "auto":
        return explicit
    # auto:ComfyUI 在跑且装好了 VFI 节点 → comfy_vfi(本机零新依赖路径)
    try:
        from hevi.providers.h3_local.comfy_client import ComfyClient

        client = ComfyClient()
        if await client.health():
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{client.base_url}/object_info")
                r.raise_for_status()
                info = r.json()
            if all(k in info for k in _VFI_NODE_CLASSES) and _model_options(info):
                return "comfy_vfi"
    except Exception as e:
        logger.info("rife auto-detect: comfy_vfi 不可用(%s),回落 vspipe/flowframes", e)
    if shutil.which("vspipe"):
        return "vspipe"
    if cfg.get("flowframes_exe") or os.getenv("POST_FLOWFRAMES_EXE"):
        return "flowframes"
    return "none"


async def interpolate_rife(
    input_path: Path | str,
    output_path: Path | str,
    *,
    config: dict[str, Any] | None = None,
    multiplier: int = 2,
    timeout_s: float = 900.0,
) -> Path:
    """RIFE 2× 插帧(纯画面)。引擎按环境自动选(见模块 docstring)。

    config 键:engine("auto"|"comfy_vfi"|"vspipe"|"flowframes")、
    model(comfy_vfi 的 frame_interpolation 模型名,默认 rife49.pth)、
    rife_kwargs(vspipe 的 core.rife.RIFE 参数)、flowframes_exe。
    """
    cfg = dict(config or {})
    inp, outp = Path(input_path), Path(output_path)
    if not inp.exists():
        raise RifeUnavailable(f"RIFE 输入不存在: {inp}")

    engine = await _resolve_engine(cfg)
    model = str(cfg.get("model") or os.getenv("POST_RIFE_MODEL") or "rife49.pth")
    fps = int(cfg.get("fps_in") or 24)

    if engine == "comfy_vfi":
        return await _run_comfy_vfi(
            inp, outp, model=model, multiplier=multiplier, fps=fps,
            client=cfg.get("client"), timeout_s=timeout_s,
        )
    if engine == "flowframes":
        exe = cfg.get("flowframes_exe") or os.getenv("POST_FLOWFRAMES_EXE", "")
        if not exe:
            raise RifeUnavailable("engine=flowframes 但未配置 POST_FLOWFRAMES_EXE")
        return await _run_flowframes(
            inp, outp, exe=str(exe), multiplier=multiplier, timeout_s=timeout_s
        )
    if engine == "vspipe":
        if shutil.which("vspipe") is None:
            raise RifeUnavailable(
                "vspipe 未安装(方案 B 需要 VapourSynth + RIFE 插件);"
                "装好后重试,或 POST_INTERP=off 跳过插帧标记 no_interp"
            )
        rife_kwargs = dict(cfg.get("rife_kwargs") or {})
        rife_kwargs.setdefault("factor_num", multiplier)
        rife_kwargs.setdefault("factor_den", 1)
        with tempfile.TemporaryDirectory(prefix="hevi_rife_") as td:
            script = Path(td) / "rife.vpy"
            script.write_text(build_vpy(input_path=inp, rife_kwargs=rife_kwargs), encoding="utf-8")
            return await _run_vspipe(script, outp, timeout_s=timeout_s)
    raise RifeUnavailable(
        "没有可用的 RIFE 引擎(comfy_vfi 需要 ComfyUI + frame_interpolation 模型;"
        "vspipe 需要 VapourSynth + RIFE 插件)。POST_INTERP=off 可跳过。"
    )
