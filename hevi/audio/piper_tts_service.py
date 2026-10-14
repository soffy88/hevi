import asyncio
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FF = '/home/soffy/.local/bin/ffmpeg'
PIPER = '/data/soffy/projects/hevi-zero/.venv/bin/piper'
VOICES = '/data/soffy/projects/hevi-zero/voices'

def piper_available() -> bool:
    return os.path.exists(PIPER)

async def synth_with_piper(
    text: str,
    output_path: str | Path,
    voice: str = "zh_CN-huayan-medium.onnx",
    speed: float = 1.0
):
    """Generate TTS using Piper (hevi-zero native engine)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not text.strip():
        proc = await asyncio.create_subprocess_exec(
            FF, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', '6.0', str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        return

    raw = str(output_path) + '.raw.wav'
    
    voice_path = Path(VOICES) / voice
    if not voice_path.exists():
        # Fallback handling just in case the voice is provided as 'zh' or 'en'
        if voice == "zh":
            voice_path = Path(VOICES) / "zh_CN-huayan-medium.onnx"
        elif voice == "en":
            voice_path = Path(VOICES) / "en_US-ryan-medium.onnx"
        else:
            voice_path = Path(VOICES) / "zh_CN-huayan-medium.onnx"

    proc = await asyncio.create_subprocess_exec(
        PIPER, '-m', str(voice_path), '-f', raw, '--length_scale', str(1 / speed),
        '--sentence_silence', '0.25',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    
    _, stderr = await proc.communicate(input=text.encode('utf-8'))
    if proc.returncode != 0:
        err_msg = stderr.decode('utf-8', errors='ignore')
        logger.error(f"Piper TTS failed: {err_msg}")
        raise RuntimeError(f"Piper TTS failed: {err_msg[-800:]}")
    
    ff_proc = await asyncio.create_subprocess_exec(
        FF, '-y', '-i', raw, '-af', 'highpass=f=70,loudnorm=I=-16:TP=-1.5', '-ar', '44100', '-ac', '2', str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    
    _, ff_stderr = await ff_proc.communicate()
    if ff_proc.returncode != 0:
        err_msg = ff_stderr.decode('utf-8', errors='ignore')
        logger.error(f"Piper FFmpeg post-processing failed: {err_msg}")
        raise RuntimeError(f"Piper FFmpeg post-processing failed: {err_msg[-800:]}")
    
    if os.path.exists(raw):
        os.remove(raw)
