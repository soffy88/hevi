"""Patch oprim (git-pinned) with the 3O SPEC §2 Task 2.2 atomic TTS prims.

3O 迁移要求把 TTS/音频合成收敛为单源原子操作,但 oprim 以固定 commit 从
git 安装(`uv.lock` 钉死),无法直接改上游源码仓库。本项目既有的
`scripts/patch_vibevoice.py` 模式:把新 prim 直接写入已安装的 site-packages,
并登记到 `oprim/__init__.py` 导出 —— 升级 oprim 后需把以下 prim 上游合入
helios-plat/oprim 仓库(函数签名与 SPEC 完全一致,平移零改动)。

新增 prims:
  oprim.edge_tts_word_boundary(text, voice, *, rate, pitch, output_path) -> dict
     单文本 edge-tts 合成 + 词级 WordBoundary 时间戳。返回
     {"audio_path": Path, "words": [{"text","start","end"}, ...]}
     (start/end 单位:秒,WordBoundary 原始 100ns 已换算)。
     取代 hevi/explainer/voiceover.py 的自写 _synthesize。

  oprim.probe_duration(path) -> float
     ffprobe 实测媒体文件时长(秒)。取代 explainer/_probe_duration、
     assembly/assembler.probe_duration、tongjian voiceover 等自写 ffprobe。

  oprim.vibevoice_tts_call(script, output_path, *, config) -> Path
     VibeVoice 合成入口:保留 hevi/audio/tts_service.py 的子进程显存隔离机制
     (worker 子进程,退出即回收 VRAM),这里仅作 3O 命名适配层(懒加载委托,
     避免 oprim↔hevi 循环导入)。

Usage:
    python scripts/patch_oprim_prims.py [venv_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

PRIMS = {
    "_edge_tts_word_boundary.py": '''\
"""oprim.edge_tts_word_boundary — 单文本 edge-tts 合成 + 词级 WordBoundary。

3O SPEC §2 Task 2.2 原子操作:取代 hevi/explainer/voiceover.py 的自写
_synthesize(同一份 edge_tts.Communicate stream + WordBoundary 逻辑)。
返回值 start/end 已从 WordBoundary 原始 100ns 单位换算为秒。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class EdgeTtsWordBoundaryError(Exception):
    """edge-tts word-boundary synthesis failed."""


async def edge_tts_word_boundary(
    text: str,
    voice: str,
    *,
    rate: str | None = None,
    pitch: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """合成单段文本并返回音频文件路径 + 词级时间戳。

    Args:
        text: 待合成文本。
        voice: edge-tts 音色 ID(如 "zh-CN-XiaoxiaoNeural")。
        rate: 语速覆盖,如 "-10%"。
        pitch: 音高覆盖,如 "+0Hz"。
        output_path: 产物落盘路径;None 时写入临时目录。

    Returns:
        {"audio_path": Path, "words": [{"text", "start", "end"}, ...]}
        (start/end 单位:秒)。

    Raises:
        EdgeTtsWordBoundaryError: edge-tts 未安装或合成无音频输出。
    """
    import edge_tts  # noqa: PLC0415

    out = Path(output_path) if output_path else None
    if out is None:
        import tempfile  # noqa: PLC0415

        out = Path(tempfile.mkdtemp(prefix="edge_tts_wb_")) / "speech.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {"boundary": "WordBoundary"}
    if rate is not None:
        kwargs["rate"] = rate
    if pitch is not None:
        kwargs["pitch"] = pitch
    communicate = edge_tts.Communicate(text, voice=voice, **kwargs)

    words: list[dict[str, Any]] = []
    audio_bytes = bytearray()
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(
                    {
                        "text": chunk["text"],
                        "start": chunk["offset"] / 1e7,
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    }
                )
    except Exception as exc:  # 网络/限流瞬时故障
        raise EdgeTtsWordBoundaryError(f"edge-tts stream failed: {exc}") from exc

    if not audio_bytes:
        raise EdgeTtsWordBoundaryError("edge-tts produced no audio data")

    out.write_bytes(bytes(audio_bytes))
    return {"audio_path": out, "words": words}
''',
    "_probe_duration.py": '''\
"""oprim.probe_duration — ffprobe 实测媒体文件时长(秒)。"""

from __future__ import annotations

import subprocess
from pathlib import Path


class ProbeDurationError(Exception):
    """ffprobe duration probing failed."""


def probe_duration(path: Path) -> float:
    """返回媒体文件真实时长(秒);探测失败抛 ProbeDurationError。"""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ProbeDurationError(f"ffprobe failed for {path}: {exc}") from exc
    try:
        return float(out.stdout.strip())
    except ValueError as exc:
        raise ProbeDurationError(f"unparsable ffprobe duration for {path}: {out.stdout!r}") from exc
''',
    "_vibevoice_tts_call.py": '''\
"""oprim.vibevoice_tts_call — VibeVoice 合成入口(子进程显存隔离)。

3O SPEC §2 Task 2.2:保留 hevi/audio/tts_service.py 的子进程显存隔离机制
(worker 子进程,退出即回收 GPU VRAM),这里以 oprim 命名提供标准入口。

懒加载委托 hevi.audio.tts_service,避免 oprim↔hevi 循环导入;hevi 侧未就绪
(如精简安装)时抛出带说明的 VibeVoiceCallError。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class VibeVoiceCallError(Exception):
    """VibeVoice synthesis via subprocess worker failed."""


async def vibevoice_tts_call(
    script: list[Any],
    output_path: Path,
    *,
    config: dict[str, Any] | None = None,
) -> Path:
    """委托 hevi/audio/tts_service 的 vibevoice worker(子进程隔离)合成。

    Args:
        script: 每行需 .text(必需);.speaker_id/.voice_ref 可选。
        output_path: 产物落盘路径。
        config: 透传 worker 配置(如 model_dir)。

    Returns:
        output_path。

    Raises:
        VibeVoiceCallError: hevi worker 不可用或合成失败。
    """
    try:
        from hevi.audio.tts_service import vibevoice_synthesize  # noqa: PLC0415
    except ImportError as exc:
        raise VibeVoiceCallError(
            "hevi.audio.tts_service unavailable (vibevoice worker not installed)"
        ) from exc
    return await vibevoice_synthesize(
        config=config or {},
        script=script,
        output_path=output_path,
    )
''',
}


def site_packages(venv: Path) -> Path:
    for p in sorted(venv.glob("lib/python*/site-packages"), reverse=True):
        return p
    raise FileNotFoundError(f"No site-packages found under {venv}")


def patch_export(init: Path) -> bool:
    """把新 prim 登记进 oprim/__init__.py 的导出(幂等 + 自愈旧引用)。"""
    text = init.read_text(encoding="utf-8")
    # 自愈:早期补丁可能写入了与子模块同名的旧引用(子模块会覆盖包属性),
    # 统一改写为下划线私有模块引用(oprim 惯例,_edge_tts_synthesize.py 等)。
    healed = (
        text.replace(
            "from oprim.edge_tts_word_boundary import edge_tts_word_boundary as _fn",
            "from oprim._edge_tts_word_boundary import edge_tts_word_boundary as _fn",
        )
        .replace(
            "from oprim.probe_duration import probe_duration as _fn",
            "from oprim._probe_duration import probe_duration as _fn",
        )
        .replace(
            "from oprim.vibevoice_tts_call import vibevoice_tts_call as _fn",
            "from oprim._vibevoice_tts_call import vibevoice_tts_call as _fn",
        )
    )
    additions = []
    if "edge_tts_word_boundary" not in text:
        additions.append(
            "def edge_tts_word_boundary(*args, **kwargs):\n"
            "    from oprim._edge_tts_word_boundary import edge_tts_word_boundary as _fn\n"
            "    return _fn(*args, **kwargs)\n"
        )
    if "probe_duration" not in text:
        additions.append(
            "def probe_duration(*args, **kwargs):\n"
            "    from oprim._probe_duration import probe_duration as _fn\n"
            "    return _fn(*args, **kwargs)\n"
        )
    if "vibevoice_tts_call" not in text:
        additions.append(
            "def vibevoice_tts_call(*args, **kwargs):\n"
            "    from oprim._vibevoice_tts_call import vibevoice_tts_call as _fn\n"
            "    return _fn(*args, **kwargs)\n"
        )
    if not additions:
        if healed != text:
            init.write_text(healed, encoding="utf-8")
            return True
        return False
    text = healed.rstrip() + "\n\n\n" + "\n".join(additions)
    init.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    venv = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".venv")
    sp = site_packages(venv)
    oprim_dir = sp / "oprim"
    if not oprim_dir.is_dir():
        print(f"oprim not found under {sp}")
        return 1
    changed = False
    for filename, content in PRIMS.items():
        target = oprim_dir / filename
        if target.exists():
            print(f"skip (already patched): {target.name}")
            continue
        target.write_text(content, encoding="utf-8")
        print(f"patched: {target.name}")
        changed = True
    if patch_export(oprim_dir / "__init__.py"):
        print("patched: oprim/__init__.py exports")
        changed = True
    if not changed:
        print("oprim prims already present — nothing to do")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
