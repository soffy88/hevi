"""P9.1.d.4 — ffmpeg adapter: transform, never generate.

ffmpeg is an **ENCODER** over the **CLI** runtime. Its input must be an existing
artifact — a file another provider produced. There is deliberately no path from a
prompt to video here, and the profile records ``text_to_video`` and
``image_generation`` in ``artifact_contract.excluded_capabilities`` so widening that is
a visible contract change.

This adapter transcodes and returns a locator. It does not probe the result: a
transcoder that measured its own output would be a second artifact authority.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers._shared import check_locator, result_for, unavailable


class FfmpegAdapter:
    """Executes `ffmpeg -i <input> <output>`. Returns a locator."""

    provider_id = "ffmpeg"

    def available(self) -> AdapterAvailability:
        binary = shutil.which("ffmpeg")
        if binary is None:
            return unavailable("ffmpeg_not_found:not on PATH")
        return AdapterAvailability(Availability.AVAILABLE)

    def execute(self, request: QualificationRequest) -> ExecutionResult:
        availability = self.available()
        if not availability.can_run:
            raise RuntimeUnavailable(availability.reason)

        if not request.input_path:
            # An encoder with nothing to encode is not a failure of ffmpeg.
            raise AdapterFailure(
                ExecutionState.NO_ARTIFACT,
                "no input artifact: ffmpeg transforms, it does not generate",
            )
        source = Path(request.input_path)
        if not source.is_file():
            raise AdapterFailure(
                ExecutionState.NO_ARTIFACT, f"input {source} does not exist"
            )

        target = Path(request.output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-pix_fmt", "yuv420p", "-c:v", "libx264",
            *list(request.params.get("extra_args", ())),
            str(target),
        ]
        import subprocess

        proc = subprocess.run(
            argv, capture_output=True, timeout=request.timeout_s, check=False,
        )
        if proc.returncode != 0:
            raise AdapterFailure(
                ExecutionState.FAILED,
                f"exit_{proc.returncode}:{proc.stderr.decode(errors='replace')[:200]}",
            )
        check_locator(request, self.provider_id)
        return result_for(
            request,
            {"runtime_class": "cli", "binary": "ffmpeg", "exit_code": "0",
             "input": str(source), "transcode": "h264/yuv420p"},
        )


__all__ = ["FfmpegAdapter"]
