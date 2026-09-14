"""Layer 4 provider-backed presenter production transaction."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from hevi.digital_human.schemas import JobStatus, PresenterJob
from hevi.digital_human.talking_face import generate_talking_face


def generate_presenter(job: PresenterJob, *, mode: str = "pilot", pilot_duration_s: float = 5.0) -> PresenterJob:
    """Generate the presenter artifact and apply HEVI job state."""
    del pilot_duration_s
    if not job.presenter_image:
        raise ValueError("presenter_image is required before presenter generation")
    if not Path(job.presenter_image).is_file():
        raise FileNotFoundError(f"presenter image not found: {job.presenter_image}")
    if not job.final_audio or not Path(job.final_audio).is_file():
        raise FileNotFoundError("final_audio must be a real file before presenter generation")
    root = Path(os.getenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", "data/digital_human")).expanduser()
    output_path = root / job.job_id / "video" / ("pilot.mp4" if mode == "pilot" else "presenter.mp4")
    asyncio.run(generate_talking_face(image_path=job.presenter_image, audio_path=job.final_audio, output_path=output_path))
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Talking Face completed without a presenter video artifact")
    job.rendered = str(output_path)
    job.status = JobStatus.PRESENTER_GENERATED
    return job
