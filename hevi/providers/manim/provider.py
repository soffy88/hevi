"""manim provider —— 代码即画面的本地视频供给。

入口与其它 video provider 一致:``caller(prompt=…, output_path=…) → Path``。

prompt 归一:
  - ManimSceneIR / dict → 编译器出源码
  - 看起来像 Python 的字符串 → 沙箱后直渲
  - 普通旁白 → draft_scene_ir 再编译

渲染优先级:本机 Manim CLI(CE 或 GL)→ ffmpeg 逐帧回退。
缺 CLI 不 pip install、不挡装配——回退仍出一张能播的「代码画面」。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from obase.provider_registry import ProviderRegistry

from hevi.prompt.manim_compiler import (
    ManimSceneIR,
    compile_manim_source,
    draft_scene_ir,
    resolve_scene_ir,
)
from hevi.providers.manim.sandbox import (
    ManimSandboxError,
    scene_class_name,
    validate_manim_source,
)

logger = logging.getLogger(__name__)

MANIM_CAPABILITY: dict[str, Any] = {
    "id": "manim",
    "capabilities": ["t2v", "code_scene", "zh_prompt"],
    "prompt_language": "zh",
    "max_duration_sec": 60,
    "resolution": ["720", "1080"],
    "ref_image": False,
    "cost_per_sec": 0,
    "health": "local_cli",
    "entrypoint": "manim",
    "vram_profile": "cpu",
    "notes": "ManimCE 无头 Cairo(默认);ManimGL 可选。缺 CLI 时 ffmpeg 逐帧回退。",
}

_QUALITY_FLAG = {"low": "-ql", "medium": "-qm", "high": "-qh", "fourk": "-qk"}


class ManimRenderError(RuntimeError):
    """Manim / 回退渲染失败。"""


def _settings_value(name: str, default: str) -> str:
    env = os.getenv(name)
    if env is not None and str(env).strip():
        return str(env).strip()
    # 不主动 import settings:缺 JWT_SECRET 时 Settings() 会 sys.exit。
    mod = sys.modules.get("hevi.core.config")
    if mod is not None:
        value = getattr(getattr(mod, "settings", None), name.lower(), None)
        if value is not None and str(value).strip() != "":
            return str(value)
    return default


def detect_manim_bin(engine: str = "ce") -> tuple[str, str] | None:
    """返回 (bin, engine)。找不到 CLI 则 None。"""
    configured = _settings_value("MANIM_BIN", "")
    wanted = (engine or _settings_value("MANIM_ENGINE", "ce")).strip().lower()
    if wanted not in {"ce", "gl", "auto"}:
        wanted = "ce"
    if configured:
        path = Path(configured)
        if path.exists():
            inferred = "gl" if "gl" in path.name else "ce"
            return configured, inferred if wanted == "auto" else wanted
    order = ("gl", "ce") if wanted == "gl" else (("ce", "gl") if wanted == "auto" else (wanted,))
    names = {"ce": ("manim",), "gl": ("manimgl", "manim-render")}
    for kind in order:
        for name in names[kind]:
            found = shutil.which(name)
            if found:
                return found, kind
    return None


def _looks_like_python(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("from ", "import ", "class ", "def "))


def _resolve_source(
    prompt: Any,
    *,
    code: str | None,
    engine: str,
    duration_s: float,
    use_mathtex: bool,
) -> tuple[str, str, ManimSceneIR | None]:
    if code and code.strip():
        source = code.strip()
        validate_manim_source(source)
        return source, scene_class_name(source), None
    is_ir = isinstance(prompt, ManimSceneIR)
    is_ir_dict = isinstance(prompt, dict) and any(
        prompt.get(key) for key in ("recipe", "tex", "scene")
    )
    if is_ir or is_ir_dict:
        ir = resolve_scene_ir(prompt, duration_s=duration_s)
        ir.use_mathtex = ir.use_mathtex or use_mathtex
        source = compile_manim_source(ir, engine=engine)
        validate_manim_source(source)
        return source, ir.scene_name, ir
    if isinstance(prompt, str) and _looks_like_python(prompt):
        source = prompt.strip()
        validate_manim_source(source)
        return source, scene_class_name(source), None
    ir = draft_scene_ir(str(prompt or ""), duration_s=duration_s)
    ir.use_mathtex = use_mathtex
    source = compile_manim_source(ir, engine=engine)
    validate_manim_source(source)
    return source, ir.scene_name, ir


def _collect_mp4(root: Path) -> Path | None:
    videos = [path for path in root.rglob("*.mp4") if path.is_file() and path.stat().st_size > 0]
    if not videos:
        return None
    return max(videos, key=lambda path: path.stat().st_mtime)


async def _run_cli(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_s: float,
) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_scrub_env(),
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ManimRenderError(f"manim 超时 {timeout_s:.0f}s") from None
    log = (stdout or b"").decode("utf-8", errors="replace")
    return int(process.returncode or 0), log


def _scrub_env() -> dict[str, str]:
    keep = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "DISPLAY",
        "XDG_RUNTIME_DIR",
        "FONTCONFIG_PATH",
        "MANIMGL_CONFIG",
    )
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONSAFEPATH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _cli_command(
    *,
    binary: str,
    engine: str,
    script: Path,
    scene: str,
    media_dir: Path,
    quality: str,
    fps: int,
    width: int,
    height: int,
) -> list[str]:
    if engine == "gl":
        return [
            binary,
            str(script),
            scene,
            "-w",
            "--file_name",
            "scene.mp4",
            "--video_dir",
            str(media_dir),
        ]
    flag = _QUALITY_FLAG.get(quality, "-qh")
    return [
        binary,
        "render",
        flag,
        f"--fps={fps}",
        f"--resolution={width},{height}",
        f"--media_dir={media_dir}",
        "-o",
        "scene.mp4",
        str(script),
        scene,
    ]


def _fallback_frames(
    ir: ManimSceneIR | None,
    dest: Path,
    *,
    width: int,
    height: int,
    fps: int,
) -> Path:
    """无 Manim CLI 时用 Pillow + ffmpeg 出逐帧动画。"""
    from hevi.providers.manim.fallback import render_fallback_scene

    return render_fallback_scene(ir, dest, width=width, height=height, fps=fps)


async def manim_generate(
    *,
    prompt: str | dict[str, Any] | ManimSceneIR = "",
    output_path: Path | str,
    code: str | None = None,
    duration_s: float = 5.0,
    width: int | None = None,
    height: int | None = None,
    fps: int = 30,
    quality: str | None = None,
    engine: str | None = None,
    timeout_s: float | None = None,
    config: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Path:
    """编译并渲染一镜 Manim 画面到 output_path。"""
    cfg = dict(config or {})
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    wanted_engine = str(engine or cfg.get("engine") or _settings_value("MANIM_ENGINE", "ce"))
    quality_name = str(quality or cfg.get("quality") or _settings_value("MANIM_QUALITY", "high"))
    try:
        raw_timeout = timeout_s or cfg.get("timeout_s") or _settings_value(
            "MANIM_TIMEOUT_S", "180"
        )
        limit = float(raw_timeout)
    except (TypeError, ValueError):
        limit = 180.0
    use_mathtex = bool(cfg.get("use_mathtex") or kwargs.get("use_mathtex"))
    if not use_mathtex:
        flag = _settings_value("MANIM_USE_MATHTEX", "0").lower()
        use_mathtex = flag in {"1", "true", "yes"}
    w = int(width or cfg.get("width") or 1920)
    h = int(height or cfg.get("height") or 1080)
    detected = detect_manim_bin(wanted_engine)
    engine_name = detected[1] if detected else ("gl" if wanted_engine == "gl" else "ce")
    try:
        source, scene, ir = _resolve_source(
            prompt,
            code=code,
            engine=engine_name,
            duration_s=float(duration_s),
            use_mathtex=use_mathtex,
        )
    except ManimSandboxError:
        raise
    except Exception as exc:
        raise ManimRenderError(f"Manim 源码编译失败: {exc}") from exc

    if detected:
        binary, engine_name = detected
        with tempfile.TemporaryDirectory(prefix="hevi-manim-") as tmp:
            work = Path(tmp)
            script = work / "scene.py"
            media = work / "media"
            media.mkdir()
            script.write_text(source, encoding="utf-8")
            cmd = _cli_command(
                binary=binary,
                engine=engine_name,
                script=script,
                scene=scene,
                media_dir=media,
                quality=quality_name,
                fps=int(fps),
                width=w,
                height=h,
            )
            logger.info("manim cli: %s", " ".join(cmd))
            try:
                code_rc, log = await _run_cli(cmd, cwd=work, timeout_s=limit)
            except ManimRenderError as exc:
                logger.warning("manim cli 失败,改走逐帧回退: %s", exc)
            else:
                produced = _collect_mp4(media) or _collect_mp4(work)
                if code_rc == 0 and produced is not None:
                    shutil.copy2(produced, outp)
                    return outp
                logger.warning("manim cli 无产物(exit=%s): %s", code_rc, log[-800:])

    logger.info("manim: CLI 不可用或未出片,使用 ffmpeg 逐帧回退")
    scene = ir or draft_scene_ir(str(prompt or ""), duration_s=float(duration_s))
    _fallback_frames(scene, outp, width=w, height=h, fps=int(fps))
    if not outp.exists() or outp.stat().st_size == 0:
        raise ManimRenderError(f"Manim 回退也未写出: {outp}")
    return outp


def register_manim() -> None:
    ProviderRegistry.register("video", "manim", manim_generate, replace=True)
    logger.info("Registered video: manim (code-as-picture, CE/GL + ffmpeg fallback)")
