"""OfflineProvider: still plate + Ken Burns + local TTS + optional Wav2Lip.

This is the no-key production path.  It never calls a paid API and always
returns a playable 9:16 clip.  Lip-sync is attempted only when a portrait
with a detectable face and the Wav2Lip ONNX model are available; any failure
falls back to Ken Burns and records the reason in ``meta``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import VideoRequest, VideoResult

FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/usr/bin/ffprobe"


def _duration(path: Path) -> float:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    )
    return float(out.strip())


def _silence(seconds: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
         f"anullsrc=r=48000:cl=stereo:d={max(0.05, seconds):.3f}", "-ar", "48000", str(out)],
        check=True,
    )
    return out


def _kenburns(image: Path, audio: Path, out: Path, duration: float, *, width: int = 1080, height: int = 1920,
              seed: int = 42) -> Path:
    fps = 30
    frames = max(2, round(duration * fps))
    zoom_in = seed % 2 == 0
    z_start, z_end = (1.0, 1.10) if zoom_in else (1.10, 1.0)
    x_expr = "iw/2-(iw/zoom/2)+sin(on/90)*iw*0.01" if seed % 3 else "iw/2-(iw/zoom/2)"
    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{z_start}+({z_end}-{z_start})*on/{frames}':"
        f"x='{x_expr}':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-loop", "1", "-i", str(image), "-i", str(audio),
         "-vf", vf, "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out)],
        check=True,
    )
    return out


class OfflineProvider:
    name = "offline"

    def available(self) -> tuple[bool, str]:
        return True, "no key needed"

    def render(self, req: VideoRequest) -> VideoResult:
        out = Path(req.output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        audio = Path(req.audio) if req.audio and Path(req.audio).is_file() else _silence(req.duration_s, out.with_suffix(".sil.wav"))
        meta = {"mode": "kenburns", "lipsync": False}
        if req.lipsync and req.lipsync_portrait and Path(req.lipsync_portrait).is_file():
            try:
                from hevi.layer4_legacy.talkcraft.omodul_impl._avatar import build_avatar_clip
                from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec

                work = out.parent / f"{out.stem}_avatar"
                work.mkdir(parents=True, exist_ok=True)
                avatar = build_avatar_clip(
                    spec=AvatarSpec(mode="lipsync", image=str(req.lipsync_portrait), engine="wav2lip"),
                    voice_wav=audio,
                    duration_s=req.duration_s,
                    work=work,
                    size=(540, 960),
                    name=f"{out.stem}_avatar.mp4",
                )
                # pad the 9:16 avatar into a 1080x1920 frame with a blurred copy
                subprocess.run(
                    [FFMPEG, "-y", "-v", "error", "-i", str(avatar.clip), "-i", str(audio),
                     "-filter_complex",
                     "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2[bg];"
                     "[0:v]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]",
                     "-map", "[v]", "-map", "1:a", "-t", f"{req.duration_s:.3f}",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-shortest", str(out)],
                    check=True,
                )
                meta = {"mode": "wav2lip", "lipsync": True, "lipsync_corr": avatar.lipsync_corr,
                        "face_score": avatar.face_score}
                return VideoResult(out, self.name, _duration(out), meta)
            except Exception as exc:
                meta["lipsync_error"] = str(exc)[:300]
        image = Path(req.image) if req.image and Path(req.image).is_file() else None
        if image is None:
            raise RuntimeError("offline provider: no still image")
        _kenburns(image, audio, out, req.duration_s, seed=req.seed)
        return VideoResult(out, self.name, _duration(out), meta)
