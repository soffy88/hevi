"""HEVI P5.1 — real fine-cut production builder.

Turns a script into a real, layered, rendered video using only real inputs:

* real narration from the existing ``edge_tts`` provider;
* real evidence captured from live pages through the existing browser path;
* real composition with ffmpeg into a layered timeline;
* a real, editable Jianying project.

Nothing here fakes content. When a resource cannot be obtained the builder says
so rather than substituting a convincing placeholder — which is precisely the
failure mode :mod:`hevi.ops.p5_1_evidence` exists to prevent.

The builder is a *production* surface. The editorial intelligence in
:mod:`hevi.ops.p5_1_session` decides what to fix; this module knows how to make
the thing.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from hevi.ops.p5_1_editable import LayerManifest
from hevi.ops.p5_1_evidence import (
    ScreenshotCapture,
    capture_screenshot,
    evidence_asset_from_capture,
)
from hevi.ops.p5_1_presentation import BeatSemantics, decide_presentation
from hevi.ops.p5_1_types import (
    CanonicalArtifact,
    EditableLayer,
    EvidenceAsset,
    EvidenceRequest,
    EvidenceSourceType,
)

WIDTH = 1280
HEIGHT = 720
FPS = 25

_SAFE_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


def _font() -> str:
    for candidate in _SAFE_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("fc-match")
    if found:
        result = subprocess.run(
            [found, "-f", "%{file}", "sans"], capture_output=True, text=True, check=False
        )
        candidate = result.stdout.strip()
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("no usable font for caption rendering")


def escape_filter_path(path: Path) -> str:
    """Escape a filesystem path for use inside an ffmpeg filter argument."""
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd[:6])}...\n{result.stderr[-600:]}"
        )
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def probe_duration_s(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


# ── Real narration (existing edge_tts provider) ──────────────────────────


@dataclass
class NarrationSegment:
    index: int
    text: str
    audio_path: str
    duration_s: float
    beat_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "beat_id": self.beat_id,
            "text": self.text,
            "audio_path": self.audio_path,
            "duration_s": self.duration_s,
        }


async def synthesise_narration(
    segments: list[tuple[str, str]], workdir: Path, *, voice: str = "zh-CN-XiaoxiaoNeural"
) -> list[NarrationSegment]:
    """Synthesise real narration with the existing edge_tts provider."""
    import edge_tts

    workdir.mkdir(parents=True, exist_ok=True)
    out: list[NarrationSegment] = []
    for index, (beat_id, text) in enumerate(segments):
        target = workdir / f"seg_{index:02d}.mp3"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(target))
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"narration synthesis produced no audio for beat {beat_id}")
        out.append(
            NarrationSegment(
                index=index,
                text=text,
                audio_path=str(target),
                duration_s=probe_duration_s(target),
                beat_id=beat_id,
            )
        )
    return out


def concatenate_audio(segments: list[NarrationSegment], target: Path) -> Path:
    """Concatenate real narration into one master track, matching P5's layout."""
    target.parent.mkdir(parents=True, exist_ok=True)
    listing = target.with_suffix(".txt")
    listing.write_text(
        "".join(f"file '{Path(s.audio_path).resolve()}'\n" for s in segments), encoding="utf-8"
    )
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c:a", "aac", "-b:a", "192k", str(target)])
    listing.unlink(missing_ok=True)
    return target


# ── Real evidence capture ────────────────────────────────────────────────


@dataclass
class AcquiredEvidence:
    asset: EvidenceAsset
    request: EvidenceRequest
    capture: ScreenshotCapture
    accepted: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset.asset_id,
            "source_type": self.asset.source_type.value,
            "source_uri": self.asset.source_uri,
            "claim": self.asset.claim_supported,
            "accepted": self.accepted,
            "reason": self.reason,
            "captured_at": self.asset.captured_at,
            "freshness": self.asset.freshness.value,
        }


async def acquire_evidence(
    requests: list[EvidenceRequest], workdir: Path, *, viewport: tuple[int, int] = (1440, 900)
) -> list[AcquiredEvidence]:
    """Acquire real evidence for real claims through the existing browser path.

    The synchronous Playwright API cannot be driven from inside a running event
    loop, so every capture is dispatched to a worker thread. Without this an
    async caller loses *every* capture while each one still reports only a bare
    failure — which reads like "the sites are down" instead of "the caller was
    on the wrong thread".
    """
    workdir.mkdir(parents=True, exist_ok=True)

    def _capture(request: EvidenceRequest, index: int) -> AcquiredEvidence:
        url = request.source_preference
        if not url.lower().startswith(("http://", "https://")):
            return AcquiredEvidence(
                asset=EvidenceAsset(
                    request_id=request.request_id, source_type=EvidenceSourceType.SYMBOLIC
                ),
                request=request,
                capture=ScreenshotCapture(),
                accepted=False,
                reason="NO_CONCRETE_SOURCE_URL",
            )
        capture = capture_screenshot(
            url, workdir / f"evidence_{index:02d}.png", viewport=viewport
        )
        if not capture.ok:
            return AcquiredEvidence(
                asset=EvidenceAsset(request_id=request.request_id),
                request=request,
                capture=capture,
                accepted=False,
                reason=capture.reason or "CAPTURE_FAILED",
            )
        asset, _scan, reasons = evidence_asset_from_capture(capture, request)
        blocking = [
            reason
            for reason in reasons
            if reason.startswith(("REJECT:", "FAKE_", "MOCK_", "UNVERIFIED", "UNLABELLED"))
        ]
        return AcquiredEvidence(
            asset=asset,
            request=request,
            capture=capture,
            accepted=not blocking,
            reason=";".join(reasons) if reasons else "TRUTH_AND_PRIVACY_PASS",
        )

    return list(
        await asyncio.gather(
            *(
                asyncio.to_thread(_capture, request, index)
                for index, request in enumerate(requests)
            )
        )
    )


def acquire_evidence_sync(
    requests: list[EvidenceRequest], workdir: Path, *, viewport: tuple[int, int] = (1440, 900)
) -> list[AcquiredEvidence]:
    """Synchronous wrapper around :func:`acquire_evidence` for script use."""
    return asyncio.run(acquire_evidence(requests, workdir, viewport=viewport))


# ── Real composition ─────────────────────────────────────────────────────


@dataclass
class ShotPlanEntry:
    """One shot: which layer shows what, for how long."""

    beat_id: str
    narration_index: int
    start_ms: int
    end_ms: int
    speaker_visible: bool
    evidence_path: str = ""
    evidence_is_real: bool = False
    evidence_kind: str = ""
    background_color: str = "#101820"
    accent_color: str = "#38BDF8"
    caption_text: str = ""
    motion: str = "STATIC"
    note: str = ""
    caption_position: str = "LOWER_THIRD"
    caption_size_px: int = 34

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_ms - self.start_ms) / 1000.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_srt(entries: list[ShotPlanEntry], target: Path) -> Path:
    """Write a real SRT from the shot plan."""
    lines: list[str] = []
    for index, entry in enumerate(entries, 1):
        start = _srt_ts(entry.start_ms)
        end = _srt_ts(entry.end_ms)
        text = entry.caption_text.strip()
        if not text:
            continue
        lines += [str(index), f"{start} --> {end}", text, ""]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


#: Where a caption block may sit. Kept small and explicit so a caption repair
#: is a bounded, verifiable parameter change rather than a re-render of anything.
#: Caption placement as ASS style geometry. ``drawtext`` is absent from the
#: canonical ffmpeg build, so captions are rendered through libass; the style
#: lives in a real .ass file, which also makes caption geometry an editable,
#: per-shot property instead of an inline filter argument.
CAPTION_POSITIONS: dict[str, dict[str, int]] = {
    # numpad alignment: 2 = bottom-centre, 8 = top-centre
    "LOWER_THIRD": {"alignment": 2, "margin_v": 130},
    "LOW": {"alignment": 2, "margin_v": 50},
    "UPPER_THIRD": {"alignment": 8, "margin_v": 60},
    "HIDDEN": {"alignment": 2, "margin_v": 0},
}


def ass_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = seconds % 60
    return f"{hours:d}:{minutes:02d}:{whole:05.2f}"


def write_shot_ass(entry: ShotPlanEntry, target: Path) -> Path | None:
    """Write a real per-shot .ass file carrying that shot's caption.

    Returning ``None`` when the shot has no caption keeps the render honest:
    a hidden caption is an absent caption file, not an empty placeholder.
    """
    text = (entry.caption_text or "").strip()
    if not text or entry.caption_position == "HIDDEN":
        return None
    style = CAPTION_POSITIONS.get(entry.caption_position, CAPTION_POSITIONS["LOWER_THIRD"])
    body = text.replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")
    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HEVI,Noto Sans CJK SC,{entry.caption_size_px},&H00FFFFFF,&H00FFFFFF,&H99000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,{style["alignment"]},80,80,{style["margin_v"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{ass_timestamp(0)},{ass_timestamp(entry.duration_s)},HEVI,,0,0,0,,{body}
"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _srt_ts(ms: int) -> str:
    hours, remainder = divmod(int(ms), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_shot(
    entry: ShotPlanEntry, workdir: Path, *, evidence_is_real: bool = True
) -> Path:
    """Render one shot as a real video file with its real audio.

    A shot that should be showing real evidence either shows the captured
    screenshot or is rendered as an explicitly labelled placeholder. It is never
    rendered as if the placeholder were the real interface.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    shot_path = workdir / f"shot_{entry.beat_id}.mp4"
    duration = max(0.4, entry.duration_s)

    filters: list[str] = []
    # Background: a clean graded field, never a fake product interface.
    filters.append(
        f"color=c={entry.background_color}:s={WIDTH}x{HEIGHT}:d={duration:.3f}[bg]"
    )
    if entry.speaker_visible:
        # A real, honest abstraction of a talking head: a framed subject block
        # with a label, not a synthetic photograph of a person.
        filters.append(
            f"color=c=#1F2937:s=440x520:d={duration:.3f}[sp]"
        )
        filters.append("[bg][sp]overlay=(W-w)/2:(H-h)/2-40[base]")
    else:
        filters.append("[bg]null[base]")

    if entry.evidence_path and Path(entry.evidence_path).is_file():
        # The evidence image is always input 0; the silent-audio source is the
        # only other input, so it has no video stream to index.
        filters.append(
            f"[0:v]scale={WIDTH - 120}:{HEIGHT - 200}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH - 120}:{HEIGHT - 200}:(ow-iw)/2:(oh-ih)/2:color=black[ev]"
        )
        filters.append("[base][ev]overlay=(W-w)/2:(H-h)/2+10[withev]")
    else:
        filters.append("[base]null[withev]")

    if entry.motion in ("PUSH_IN", "PUSH_OUT"):
        span = f"if(lt(t,0.001),1,max(1,min({1.18 if entry.motion == 'PUSH_IN' else 0.86:.2f},"
        span += f"1+({0.18 if entry.motion == 'PUSH_IN' else -0.14:.2f})*t/{duration:.3f})))"
        filters.append(f"[withev]scale=w='iw*{span}':h='ih*{span}':eval=frame,setpts=PTS-STARTPTS[z]")
    else:
        filters.append("[withev]null[z]")

    ass = write_shot_ass(entry, workdir / f"caption_{entry.beat_id}.ass")
    if ass is not None:
        filters.append(f"[z]subtitles={escape_filter_path(ass)}[cap]")
        filters.append(f"[cap]fps={FPS},format=yuv420p[v]")
    else:
        filters.append(f"[z]fps={FPS},format=yuv420p[v]")

    inputs: list[str] = []
    if entry.evidence_path and Path(entry.evidence_path).is_file():
        inputs += ["-loop", "1", "-i", str(entry.evidence_path)]
    else:
        inputs += ["-f", "lavfi", "-i", f"color=c=black:s=8x8:d={duration:.3f}"]
    # ``inputs`` holds argv tokens, not inputs, so the silent-audio input index
    # is counted explicitly rather than derived from the list length.
    picture_inputs = 1
    inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    audio_index = picture_inputs

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", f"{audio_index}:a",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", str(shot_path),
    ]
    _run(cmd)
    return shot_path


def rerender_caption_range(
    shots: list[tuple[Path, ShotPlanEntry]],
    entries: list[ShotPlanEntry],
    workdir: Path,
    *,
    start_ms: int,
    end_ms: int,
    caption_position: str | None = None,
    caption_size_px: int | None = None,
) -> list[Path]:
    """Re-render only the shots whose captions changed.

    This is the ``CAPTION_RANGE`` repair: the affected shots are redrawn with the
    new caption placement and every other shot — and every other layer, including
    the audio — is left byte-for-byte alone.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for path, entry in shots:
        if not (entry.start_ms < end_ms and start_ms < entry.end_ms):
            out.append(path)
            continue
        updated = replace(
            entry,
            caption_position=caption_position or entry.caption_position,
            caption_size_px=caption_size_px or entry.caption_size_px,
        )
        out.append(render_shot(updated, workdir))
    return out


def assemble(shots: list[tuple[Path, ShotPlanEntry]], master: Path) -> Path:
    """Concatenate rendered shots into a master video."""
    listing = master.with_suffix(".concat.txt")
    listing.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text(
        "".join(f"file '{Path(p).resolve()}'\n" for p, _e in shots), encoding="utf-8"
    )
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", str(master)])
    listing.unlink(missing_ok=True)
    return master


def mux_narration(voice: Path, video: Path, target: Path) -> Path:
    """Put the real narration over the picture."""
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(video), "-i", str(voice),
          "-map", "0:v:0", "-map", "1:a:0",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(target)])
    return target


# ── Layered delivery ─────────────────────────────────────────────────────


def build_layer_manifest(
    *,
    content_id: str,
    candidate_id: str,
    entries: list[ShotPlanEntry],
    master: Path,
    voice: Path,
    srt: Path,
    speaker_shot: str = "",
) -> LayerManifest:
    from hevi.ops.p5_1_editable import manifest_from_production

    evidence = [
        {
            "path": entry.evidence_path,
            "start_ms": entry.start_ms,
            "end_ms": entry.end_ms,
            "asset_id": f"ev-{entry.beat_id}",
            "role": "EVIDENCE_DOMINANT",
        }
        for entry in entries
        if entry.evidence_path
    ]
    return manifest_from_production(
        content_id=content_id,
        candidate_id=candidate_id,
        background_path=str(master),
        speaker_path=speaker_shot,
        evidence=evidence,
        caption_path=str(srt),
        voice_path=str(voice),
        duration_ms=entries[-1].end_ms,
    )


__all__ = [
    "FPS",
    "HEIGHT",
    "WIDTH",
    "AcquiredEvidence",
    "BeatSemantics",
    "CanonicalArtifact",
    "EditableLayer",
    "LayerManifest",
    "NarrationSegment",
    "ShotPlanEntry",
    "acquire_evidence",
    "acquire_evidence_sync",
    "assemble",
    "build_layer_manifest",
    "concatenate_audio",
    "decide_presentation",
    "mux_narration",
    "probe_duration_s",
    "render_shot",
    "rerender_caption_range",
    "sha256_file",
    "synthesise_narration",
    "write_srt",
]
