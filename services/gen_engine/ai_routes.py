# ruff: noqa: B008  # FastAPI File()/Form() 默认值是框架规范写法
"""hevi-gen-engine 统一 AI 端点 —— /api/ai/*

CosyVoice TTS 与 LongCat Talking Face 的推理入口, 全部在 GPU 引擎容器内
执行(模型加载 / 显存隔离子进程 / 权重落盘都在这里)。hevi-api 只做 HTTP 调用。

能力探测约定:
    GET /api/ai/capabilities  -> {"cosyvoice": bool, "longcat": bool, "vibevoice": bool}
    客户端据此决定是否走引擎, 否则用本地降级路径。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── 能力探测 ──────────────────────────────────────────────────────


def _cosyvoice_model_dir() -> Path | None:
    raw = os.environ.get("COSYVOICE_MODEL_DIR", "").strip()
    if raw:
        p = Path(raw)
        if p.is_dir() and any(p.iterdir()):
            return p
    return None


def _cosyvoice3_model_dir() -> Path | None:
    """Fun-CosyVoice3-0.5B(多语言, cosyvoice3.yaml 布局)。"""
    for raw in (
        os.environ.get("COSYVOICE3_MODEL_DIR", "").strip(),
        os.environ.get("FUN_COSYVOICE3_MODEL_DIR", "").strip(),
    ):
        if raw:
            p = Path(raw)
            if p.is_dir() and any(p.iterdir()):
                return p
    return None


def _f5_tts_model_dir() -> Path | None:
    """F5-TTS 模型目录: 需 F5TTS_Base/model_1200000.safetensors 才算部署。"""
    raw = os.environ.get("F5_TTS_MODEL_DIR", "/models/f5-tts").strip()
    p = Path(raw)
    if (p / "F5TTS_Base" / "model_1200000.safetensors").is_file():
        return p
    return None


def _vibevoice_model_dir() -> Path | None:
    raw = os.environ.get("VIBEVOICE_MODEL_DIR", "/models/vibevoice-1.5b").strip()
    p = Path(raw)
    if p.is_dir() and any(p.iterdir()):
        return p
    return None


def _fish_speech_model_dir() -> Path | None:
    raw = os.environ.get("FISH_SPEECH_MODEL_DIR", "/models/fish-speech-1.5").strip()
    p = Path(raw)
    if p.is_dir() and (p / "model.pth").exists():
        return p
    return None


def _longcat_model_dir() -> Path | None:
    for candidate in (
        os.environ.get("LONGCAT_MODEL_PATH", ""),
        os.environ.get("ECHOMIMIC_MODEL_PATH", ""),
        "/data/models/LongCat-Voice",
        "/data/models/echo-mimic",
    ):
        if not candidate:
            continue
        p = Path(candidate).expanduser()
        if p.is_dir() and any(p.iterdir()):
            return p
    return None


def capabilities() -> dict[str, bool]:
    return {
        "cosyvoice": _cosyvoice_model_dir() is not None,
        "cosyvoice3": _cosyvoice3_model_dir() is not None,
        "f5_tts": _f5_tts_model_dir() is not None,
        "vibevoice": _vibevoice_model_dir() is not None,
        "longcat": _longcat_model_dir() is not None,
        "fish_speech": _fish_speech_model_dir() is not None,
    }


@router.get("/capabilities")
async def get_capabilities() -> dict[str, Any]:
    caps: dict[str, Any] = capabilities()
    caps["engine"] = "hevi-gen-engine"
    caps["version"] = "1.0.0"
    return caps


@router.get("/health")
async def health() -> dict[str, Any]:
    gpu: bool = False
    gpu_name: str | None = None
    try:
        import torch

        gpu = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if gpu else None
    except Exception:
        pass
    return {
        "status": "ok",
        "gpu": gpu,
        "gpu_name": gpu_name,
        **capabilities(),
    }


# ─── CosyVoice TTS ─────────────────────────────────────────────────


def _ai_python() -> str:
    """优先独立 ai-venv(隔离 vibevoice 的严格版本钉), 否则回退系统 python。"""
    candidate = "/opt/ai-venv/bin/python"
    return candidate if Path(candidate).exists() else sys.executable


def _asr_python() -> str:
    """ASR 专用 venv(transformers>=5.3.0 官方类), 缺失回退 ai-venv。"""
    candidate = "/opt/asr-venv/bin/python"
    if Path(candidate).exists():
        return candidate
    return _ai_python()


def _cosy_python() -> str:
    """CosyVoice 专用 venv(transformers==5.13.0 + 重供货 cosyvoice), 缺失回退 ai-venv。"""
    candidate = "/opt/cosy-venv/bin/python"
    if Path(candidate).exists():
        return candidate
    return _ai_python()


async def _run_worker_async(worker: Path, args: dict[str, Any], *, python: str) -> tuple[int, str]:
    """子进程 worker: (returncode, stdout)。stderr 并入 stdout。"""
    args_path = Path(tempfile.mkdtemp(prefix="hevi-ai-worker-")) / "args.json"
    args_path.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        python, str(worker), str(args_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    code = proc.returncode if proc.returncode is not None else -1
    return code, stdout.decode(errors="replace") if stdout else ""


@router.post("/cosyvoice")
async def synthesize_cosyvoice(payload: dict[str, Any]) -> Response:
    """CosyVoice 风格解说 TTS(引擎侧合成)。

    Body: {"script": [{"text": str, "speaker_id"?: str, "voice_ref"?: str}],
           "config": {"model_dir"?: str, "watermark"?: bool}}
    引擎内合成优先级:
      1. oprim.cosyvoice_tts_call —— 若引擎镜像安装了 oprim 且 CosyVoice 模型就位
      2. vibevoice 子进程(显存隔离) —— VIBEVOICE_MODEL_DIR 就位
      3. 501 —— 模型未部署(客户端降级)
    """
    script = payload.get("script") or []
    if not script:
        raise HTTPException(status_code=422, detail="script 不能为空")
    config = payload.get("config") or {}
    watermark = bool(config.get("watermark", True))
    requested_model = str(config.get("model_dir") or "").strip()

    # 1) oprim 原生 CosyVoice 原子(若已安装并部署模型)
    if requested_model and Path(requested_model).is_dir():
        try:
            import oprim

            provider = getattr(oprim, "cosyvoice_tts_call", None)
        except ImportError:
            provider = None
        if provider is not None:
            with tempfile.TemporaryDirectory(prefix="hevi-ai-") as tmp:
                out = Path(tmp) / "cosyvoice.wav"
                result = provider(
                    config={"COSYVOICE_MODEL_DIR": requested_model},
                    script=script,
                    output_path=out,
                    watermark=watermark,
                )
                if asyncio.iscoroutine(result):
                    result = await result
                path = Path(result or out)
                if path.is_file() and path.stat().st_size > 0:
                    return Response(
                        content=path.read_bytes(),
                        media_type="audio/wav",
                        headers={"X-Engine": "oprim-cosyvoice"},
                    )

    # 2) 重供货 CosyVoice2/3 worker(cosy-venv, transformers==5.13 + 行为补丁)
    #    —— 需要 voice_ref 克隆音色; 失败降级 vibevoice, 不阻断。
    has_voice_ref = any(line.get("voice_ref") for line in script)
    model_choice = str(config.get("model") or "").strip()
    if model_choice in ("Fun-CosyVoice3-0.5B", "CosyVoice3"):
        cosy_model_dir = _cosyvoice3_model_dir() or requested_model or None
    else:
        cosy_model_dir = requested_model or _cosyvoice_model_dir() or None

    if has_voice_ref and cosy_model_dir is not None:
        worker = Path(__file__).resolve().parent / "cosy_worker.py"
        # voice_ref 必须是引擎容器内可见路径(跨容器宿主路径不可达)。
        refs_ok = all(
            not (line.get("voice_ref") and not Path(str(line["voice_ref"])).exists())
            for line in script
        )
        if refs_ok:
            tmp_out = Path(tempfile.mkdtemp(prefix="hevi-ai-cosy-")) / "cosyvoice.wav"
            args = {
                "script": [
                    {
                        "speaker_id": line.get("speaker_id", "host"),
                        "text": line.get("text", str(line)),
                        "voice_ref": line.get("voice_ref"),
                        "ref_text": line.get("ref_text"),
                        "speed": line.get("speed", 1.0),
                    }
                    for line in script
                ],
                "output_path": str(tmp_out),
                "model_dir": str(cosy_model_dir),
            }
            try:
                code, worker_out = await _run_worker_async(worker, args, python=_cosy_python())
                if code == 0 and tmp_out.is_file() and tmp_out.stat().st_size > 0:
                    model_tag = Path(str(cosy_model_dir)).name
                    logger.info("cosy worker OK (%s) → %s", model_tag, tmp_out.name)
                    return Response(
                        content=tmp_out.read_bytes(),
                        media_type="audio/wav",
                        headers={"X-Engine": "cosyvoice-worker"},
                    )
                logger.warning("cosy worker exit=%s, 降级 vibevoice: %s", code, worker_out[-400:])
            except Exception as exc:
                logger.warning("cosy worker 异常, 降级 vibevoice: %s", exc)

    # 3) vibevoice 子进程(独立 ai-venv, 显存隔离)
    model_dir = _vibevoice_model_dir()
    if model_dir is None and requested_model:
        probe = Path(requested_model)
        if probe.is_dir() and any(probe.iterdir()):
            model_dir = probe
    if model_dir is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "AI 引擎未部署 CosyVoice/VibeVoice 模型: 设置 COSYVOICE_MODEL_DIR 或 "
                "VIBEVOICE_MODEL_DIR 并挂载权重后重启引擎容器。"
            ),
        )

    # vibevoice 0.0.1 每次生成强制要求 voice_samples(参考音频), 无参考音频
    # 会在 generate() 崩 'NoneType' .to —— 前置检查给客户端友好 501。
    has_voice_ref = any(line.get("voice_ref") for line in script)
    if not has_voice_ref:
        raise HTTPException(
            status_code=501,
            detail=(
                "vibevoice 引擎需要 voice_ref 参考音频(每次生成强制要求 voice_samples); "
                "请在 script 行提供 voice_ref, 或部署真实 CosyVoice 模型 "
                "(COSYVOICE_MODEL_DIR)。"
            ),
        )
    # v9.1: voice_ref 必须是引擎容器内可见路径(宿主路径跨容器不可达)。
    for line in script:
        ref = str(line.get("voice_ref") or "")
        if ref and not Path(ref).exists():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"voice_ref 在引擎容器内不可达: {ref}; "
                    "请上传参考音频到引擎可访问路径(如 /app/data/generations/)"
                ),
            )

    with tempfile.TemporaryDirectory(prefix="hevi-ai-tts-") as tmp:
        tmp_dir = Path(tmp)
        args_path = tmp_dir / "args.json"
        out_path = tmp_dir / "cosyvoice.wav"
        args_path.write_text(
            json.dumps(
                {
                    "script": [
                        {
                            "speaker_id": line.get("speaker_id", "host"),
                            "text": line.get("text", str(line)),
                            "voice_ref": line.get("voice_ref"),
                        }
                        for line in script
                    ],
                    "output_path": str(out_path),
                    "model_dir": str(model_dir),
                    "watermark": watermark,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        worker = Path(__file__).resolve().parent / "tts_worker.py"
        proc = await asyncio.create_subprocess_exec(
            _asr_python(), str(worker), str(args_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            tail = stdout.decode(errors="replace")[-600:] if stdout else ""
            logger.error("gen-engine tts_worker failed: %s", tail)
            raise HTTPException(
                status_code=500,
                detail=f"AI 引擎合成失败 (exit={proc.returncode}): {tail}",
            )
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="AI 引擎未产出音频")
        return Response(
            content=out_path.read_bytes(),
            media_type="audio/wav",
            headers={"X-Engine": "vibevoice"},
        )


# ─── F5-TTS 零样本音色克隆 ──────────────────────────────────────────


@router.post("/f5_tts")
async def synthesize_f5_tts(
    text: str = Form(...),
    reference_text: str = Form(...),
    reference_audio: UploadFile = File(...),
    speed: float = Form(1.0),
    seed: int | None = Form(None),
) -> Response:
    """F5-TTS 零样本音色克隆(引擎侧合成)。

    - reference_audio: 参考音频(必填, 克隆音色, ≤12s 自动截断)
    - reference_text: 参考音频的转录文本(必填; 生产容器离线, 不自动转写)
    - 模型: SWivid/F5-TTS(F5TTS_Base) + charactr/vocos-mel-24khz,
      目录见 F5_TTS_MODEL_DIR(缺模型时 501, 客户端降级)。
    """
    model_dir = _f5_tts_model_dir()
    if model_dir is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "F5-TTS 模型未部署: F5_TTS_MODEL_DIR 下缺 "
                "F5TTS_Base/model_1200000.safetensors (见 docs/VOICEBOX-INTEGRATION.md)"
            ),
        )
    if not text.strip():
        raise HTTPException(status_code=422, detail="text 不能为空")
    if not reference_text.strip():
        raise HTTPException(
            status_code=422,
            detail="reference_text 必填(参考音频的转录文本; 生产容器离线不自动转写)",
        )
    if not 0.5 <= float(speed) <= 2.0:
        raise HTTPException(status_code=422, detail="speed 应在 0.5~2.0")

    tmp = Path(tempfile.mkdtemp(prefix="hevi-ai-f5-"))
    ref_path = tmp / "ref.wav"
    ref_path.write_bytes(await reference_audio.read())
    out_path = tmp / "speech.wav"
    worker = Path(__file__).resolve().parent / "f5_worker.py"
    code, out = await _run_worker_async(
        worker,
        {
            "text": text,
            "reference_audio": str(ref_path),
            "reference_text": reference_text,
            "output_path": str(out_path),
            "model_dir": str(model_dir),
            "seed": seed,
            "speed": float(speed),
        },
        python=_ai_python(),
    )
    if code != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise HTTPException(
            status_code=500,
            detail=f"F5-TTS 合成失败 (exit={code}): {out[-600:]}",
        )
    return Response(
        content=out_path.read_bytes(),
        media_type="audio/wav",
        headers={"X-Engine": "f5-tts"},
    )


# ─── LongCat Talking Face ──────────────────────────────────────────


@router.post("/longcat")
async def generate_longcat(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    preset_name: str = Form("default"),
    gpu_id: int = Form(0),
) -> Response:
    """LongCat-Video Talking Face: 播音员照片 + 主音频 → 等长口型视频。

    multipart: image(jpg/png), audio(wav/mp3)。引擎内跑
    `python -m longcat.run` 子进程(模型由 LONGCAT_MODEL_PATH 指定)。
    模型未部署 → 501(客户端降级到本地 ffmpeg 占位动画)。
    """
    model_dir = _longcat_model_dir()
    if model_dir is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "AI 引擎未部署 LongCat 模型: 挂载 LongCat-Video 权重并设置 "
                "LONGCAT_MODEL_PATH 后重启引擎容器。"
            ),
        )

    image_bytes = await image.read()
    audio_bytes = await audio.read()
    if not image_bytes or not audio_bytes:
        raise HTTPException(status_code=422, detail="image 与 audio 不能为空")

    with tempfile.TemporaryDirectory(prefix="hevi-ai-longcat-") as tmp:
        tmp_dir = Path(tmp)
        img_path = tmp_dir / "presenter.jpg"
        aud_path = tmp_dir / "master.wav"
        out_path = tmp_dir / "talking_face.mp4"
        img_path.write_bytes(image_bytes)
        aud_path.write_bytes(audio_bytes)

        env = dict(os.environ)
        env.update(
            {
                "LONGCAT_MODEL_PATH": str(model_dir),
                "CUDA_VISIBLE_DEVICES": str(gpu_id),
            }
        )
        cmd = [
            sys.executable, "-m", "longcat.run",
            "--image", str(img_path),
            "--audio", str(aud_path),
            "--output", str(out_path),
            "--preset", preset_name,
        ]
        logger.info("LongCat: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            tail = stderr.decode(errors="replace")[-600:] or stdout.decode(errors="replace")[-600:]
            logger.error("LongCat failed: %s", tail)
            raise HTTPException(
                status_code=500,
                detail=f"LongCat 推理失败 (exit={proc.returncode}): {tail}",
            )
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="LongCat 未产出视频")

        return Response(
            content=out_path.read_bytes(),
            media_type="video/mp4",
            headers={"X-Engine": "longcat"},
        )


# ─── fish-speech 1.5 TTS ──────────────────────────────────────────


@router.post("/fish_speech")
async def synthesize_fish_speech(
    text: str = Form(...),
    reference_audio: UploadFile | None = File(None),
) -> Response:
    """fish-speech-1.5 零样本 TTS: 文本 + 可选参考音频 → wav。

    推理在独立 ai-venv 子进程(fish_worker.py)执行 —— fish-speech 依赖
    (audiotools 等)与 voicebox 主环境冲突, 必须隔离; 子进程退出即回收显存。
    模型未部署(FISH_SPEECH_MODEL_DIR) → 501, 客户端降级。
    """
    model_dir = _fish_speech_model_dir()
    if model_dir is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "AI 引擎未部署 fish-speech 模型: 挂载 fish-speech-1.5 权重并设置 "
                "FISH_SPEECH_MODEL_DIR 后重启引擎容器。"
            ),
        )
    if not text.strip():
        raise HTTPException(status_code=422, detail="text 不能为空")

    with tempfile.TemporaryDirectory(prefix="hevi-ai-fish-") as tmp:
        tmp_dir = Path(tmp)
        args_path = tmp_dir / "args.json"
        out_path = tmp_dir / "speech.wav"
        ref_path: str | None = None
        if reference_audio is not None:
            ref_bytes = await reference_audio.read()
            if ref_bytes:
                ref_path = str(tmp_dir / "reference.wav")
                (tmp_dir / "reference.wav").write_bytes(ref_bytes)

        args_path.write_text(
            json.dumps(
                {
                    "text": text,
                    "model_dir": str(model_dir),
                    "reference_audio": ref_path,
                    "output_path": str(out_path),
                    "max_new_tokens": 512,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        worker = Path(__file__).resolve().parent / "fish_worker.py"
        proc = await asyncio.create_subprocess_exec(
            _ai_python(), str(worker), str(args_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            tail = stdout.decode(errors="replace")[-600:] if stdout else ""
            logger.error("fish_worker failed: %s", tail)
            raise HTTPException(
                status_code=500,
                detail=f"fish_speech 推理失败 (exit={proc.returncode}): {tail}",
            )
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="fish_speech 未产出音频")
        return Response(
            content=out_path.read_bytes(),
            media_type="audio/wav",
            headers={"X-Engine": "fish_speech"},
        )


# ─── VibeVoice-ASR 长文识别(说话人 + 时间戳 + 热词) ─────────────────────


def _vibevoice_asr_model_dir() -> Path | None:
    raw = os.environ.get("VIBEVOICE_ASR_MODEL_DIR", "/models/vibevoice-asr").strip()
    p = Path(raw)
    if p.is_dir() and any(p.iterdir()):
        return p
    return None


@router.post("/asr")
async def transcribe_asr(
    audio: UploadFile = File(...),
    language: str = Form("auto"),
    hotwords: str = Form(""),
) -> Response:
    """VibeVoice-ASR: 长文语音识别 → 说话人/时间戳/内容 JSON。

    推理在独立 ai-venv 子进程(asr_worker.py)执行 —— vibevoice 含 ASR 模块,
    与 voicebox 主环境隔离; 子进程退出即释放显存。
    模型未部署(VIBEVOICE_ASR_MODEL_DIR) → 501, 客户端降级 faster-whisper。
    """
    model_dir = _vibevoice_asr_model_dir()
    if model_dir is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "AI 引擎未部署 VibeVoice-ASR 模型: 下载 microsoft/VibeVoice-ASR "
                "并设置 VIBEVOICE_ASR_MODEL_DIR 后重启引擎容器。"
            ),
        )
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="audio 不能为空")

    hotword_list = [h.strip() for h in hotwords.split(",") if h.strip()]

    with tempfile.TemporaryDirectory(prefix="hevi-ai-asr-") as tmp:
        tmp_dir = Path(tmp)
        audio_path = tmp_dir / "input.wav"
        audio_path.write_bytes(audio_bytes)
        args_path = tmp_dir / "args.json"
        out_json = tmp_dir / "out.json"
        args_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path),
                    "vae_model": str(model_dir / "vibeasr-vae-encoder-i8_s.gguf"),
                    "lm_model": str(model_dir / "vibeasr-lm-i2_s-embed-q6_k.gguf"),
                    "hotwords": hotword_list,
                    "language": language,
                    "output_json": str(out_json),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        worker = Path(__file__).resolve().parent / "asr_worker.py"
        proc = await asyncio.create_subprocess_exec(
            _asr_python(), str(worker), str(args_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            tail = stdout.decode(errors="replace")[-600:] if stdout else ""
            logger.error("asr_worker failed: %s", tail)
            raise HTTPException(
                status_code=500,
                detail=f"VibeVoice-ASR 推理失败 (exit={proc.returncode}): {tail}",
            )
        if not out_json.exists():
            raise HTTPException(status_code=500, detail="VibeVoice-ASR 未产出结果")
        content = out_json.read_bytes()

    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Engine": "vibevoice-asr"},
    )


