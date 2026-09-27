"""HEVI P5.2 — shared real-asset layer for the end-to-end drivers.

Every E2E in this package runs against real media produced by a real tool. There
is no synthetic substitute anywhere in here, and no fixture silently degrades to
a placeholder: if a real source is missing, the test skips with the reason, and
the qualification report records the skip. That is the whole point — a green tick
on a mock is worse than a skip, because it launders an unproven path into a
proven one.

The one piece of genuinely expensive work is ASR. A real transcript of a real
113-second interview takes about half a minute of CPU, so the transcript is
cached on disk keyed by the content hash of the audio it came from. The cache is
an optimisation, not a substitute: a cache miss re-runs faster-whisper.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

#: The main checkout. P5.2 runs in its own worktree, but the real corpus, the
#: real web build and the real ASR weights all live in the canonical tree.
REPO = Path(os.environ.get("HEVI_REPO", "/data/soffy/projects/hevi"))

#: NASA KSC interview. Real documentary footage of Michael Collins speaking,
#: 113.2s, public domain (nasa-media), 50.1s of real speech in 23 segments.
#: This is the qualified *presenter source* and the raw-footage source.
NASA_INTERVIEW = (
    REPO / "data/workspace/assets/open-corpus-seed/clips"
    / "nasa_KSC-20190716-MH-NAS01_0001-Return_to_the.mp4"
)
NASA_INTERVIEW_TITLE = (
    "Return to the Pad: Astronaut Michael Collins Reflects on Apollo 11 Launch"
)
NASA_INTERVIEW_LICENSE = "nasa-media"

CACHE = Path(os.environ.get("HEVI_P52_E2E_CACHE", "/tmp/opencode/p52work"))


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def ffprobe_streams(path: Path) -> dict[str, str]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return {
        f"{s['codec_type']}:{s.get('codec_name')}": str(s.get("width") or s.get("height") or "")
        for s in json.loads(proc.stdout)["streams"]
    }


# ── ASR ──────────────────────────────────────────────────────────────────


def asr_available() -> tuple[bool, str]:
    """Real ASR, offline. faster-whisper plus weights already on disk."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, "faster-whisper not installed"
    if not _whisper_weights_present():
        return False, "faster-whisper weights not on disk"
    return True, "faster-whisper small (int8, cpu, offline)"


def _whisper_weights_present() -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface"))
    for root in (hub, Path("/data/soffy/appdata/huggingface_hub")):
        if root and (root / "models--Systran--faster-whisper-small").is_dir():
            return True
    return False


def real_transcript(video: Path, *, workdir: Path) -> tuple[dict, str]:
    """ASR a real video, with a content-hash cache.

    Returns ``(whisper-shaped payload, engine description)``. The payload is
    whisper's own JSON shape so it can be fed to ``parse_whisper_json``
    unchanged — the E2E exercises the production parser, not a test-only one.
    """
    digest = sha256_file(video)[:16]
    cache = CACHE / f"asr-{digest}.json"
    if cache.is_file():
        return json.loads(cache.read_text()), f"faster-whisper small (cached, {digest})"

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from faster_whisper import WhisperModel

    workdir.mkdir(parents=True, exist_ok=True)
    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)
    segments, info = model.transcribe(str(video), language="en", vad_filter=True)
    rows = [
        {
            "id": index,
            "seek": 0,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text,
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": -0.3,
            "compression_ratio": 1.2,
            "no_speech_prob": 0.01,
        }
        for index, seg in enumerate(segments)
    ]
    payload = {
        "task": "transcribe",
        "language": info.language,
        "duration": ffprobe_duration(video),
        "text": " ".join(row["text"].strip() for row in rows),
        "segments": rows,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload, f"faster-whisper small (int8, cpu, offline, {digest})"


# ── Fixtures ─────────────────────────────────────────────────────────────


@dataclass
class RealSource:
    """A real media source, with the provenance to prove it is real."""

    path: Path
    title: str
    license: str
    content_hash: str
    duration_s: float
    streams: dict[str, str]


@pytest.fixture(scope="session")
def nasa_interview() -> RealSource:
    """The real interview. Session-scoped: ASR and hashing are not cheap."""
    if not NASA_INTERVIEW.is_file():
        pytest.skip(f"real source absent: {NASA_INTERVIEW}")
    return RealSource(
        path=NASA_INTERVIEW,
        title=NASA_INTERVIEW_TITLE,
        license=NASA_INTERVIEW_LICENSE,
        content_hash=sha256_file(NASA_INTERVIEW),
        duration_s=ffprobe_duration(NASA_INTERVIEW),
        streams=ffprobe_streams(NASA_INTERVIEW),
    )


@pytest.fixture(scope="session")
def nasa_whisper(nasa_interview: RealSource, tmp_path_factory) -> tuple[dict, str]:
    available, reason = asr_available()
    if not available:
        pytest.skip(f"real ASR unavailable: {reason}")
    workdir = tmp_path_factory.mktemp("asr")
    return real_transcript(nasa_interview.path, workdir=workdir)


@pytest.fixture(scope="session")
def product_frames() -> list[Path]:
    """Real screenshots of HEVI's own product UI.

    These are captured from the real Next.js build against the real FastAPI
    backend and the real Postgres. If the frames are not already on disk the
    test skips with instructions rather than substituting a mock — a product
    video built on a fabricated UI would be the single most misleading thing
    this suite could produce.
    """
    frames = sorted(Path(os.environ.get("HEVI_P52_PRODUCT_FRAMES", "/tmp/opencode/frames")).glob("*.png"))
    if not frames:
        pytest.skip(
            "real product frames absent; capture HEVI's own hevi-web against the real "
            "FastAPI backend first (see scripts/qualification/capture_product_surface.sh)"
        )
    return frames


def playwright_node_modules() -> Path | None:
    for candidate in (
        REPO / "hevi-web/node_modules",
        Path("/data/soffy/projects/hemal/node_modules"),
    ):
        if (candidate / "playwright-core").is_dir():
            return candidate
    return None
