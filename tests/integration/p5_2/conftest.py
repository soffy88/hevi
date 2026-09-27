"""Fixtures for the P5.2 end-to-end drivers.

All of them resolve to real media produced by a real tool. When a real source is
absent the fixture skips with the reason; it never substitutes a synthetic stand-in.
A tick on a mock would launder an unproven path into a proven one, which is the
opposite of what an end-to-end test is for.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_2_real_assets import (
    NASA_INTERVIEW,
    NASA_INTERVIEW_LICENSE,
    NASA_INTERVIEW_TITLE,
    RealSource,
    asr_available,
    ffprobe_duration,
    ffprobe_streams,
    real_transcript,
    sha256_file,
)

__all__ = [
    "NASA_INTERVIEW",
    "NASA_INTERVIEW_LICENSE",
    "NASA_INTERVIEW_TITLE",
    "RealSource",
    "asr_available",
    "ffprobe_duration",
    "ffprobe_streams",
    "nasa_interview",
    "nasa_whisper",
    "playwright_node_modules",
    "product_frames",
    "real_transcript",
    "sha256_file",
]


@pytest.fixture(scope="session", autouse=True)
def registered_backends() -> tuple[list[str], list[str]]:
    """Register the real renderer and editable-backend registries once.

    Registration is explicit by design, so a test that forgets it gets an honest
    NO_RENDERER_AVAILABLE rather than silently reaching a backend it never asked
    for. Doing it in an autouse session fixture keeps that explicitness in the
    production code where it belongs.
    """
    from hevi.editable import register_all_backends
    from hevi.renderers import register_all_renderers

    return register_all_renderers(), register_all_backends()


@pytest.fixture(scope="session")
def nasa_interview() -> RealSource:
    """A real interview: Michael Collins, 113.2s, public domain, 50.1s of speech."""
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
    """A real ASR transcript of the real interview, produced offline by faster-whisper."""
    available, reason = asr_available()
    if not available:
        pytest.skip(f"real ASR unavailable: {reason}")
    workdir: Path = tmp_path_factory.mktemp("asr")
    return real_transcript(nasa_interview.path, workdir=workdir)


@pytest.fixture(scope="session")
def product_frames() -> list[Path]:
    """Real screenshots of HEVI's own product UI.

    Captured from the real prebuilt Next.js app against the real FastAPI backend
    and the real database. Absent frames mean a skip, never a mock: a product
    video built on a fabricated UI would be the most misleading artifact this
    suite could produce.
    """
    import os

    frames = sorted(
        Path(os.environ.get("HEVI_P52_PRODUCT_FRAMES", "/tmp/opencode/frames")).glob("*.png")
    )
    if not frames:
        pytest.skip(
            "real product frames absent; run scripts/qualification/capture_product_surface.sh "
            "to capture HEVI's own hevi-web against the real FastAPI backend"
        )
    return frames


def playwright_node_modules() -> Path | None:
    """Locate a real playwright-core, for rendering HTML/GSAP and capturing UI."""
    from p5_2_real_assets import playwright_node_modules as locate

    return locate()
