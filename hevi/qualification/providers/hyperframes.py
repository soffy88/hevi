"""P9.1.e — HyperFrames adapter: execute only, under a declared timeout contract.

## What the runtime audit found

The `hyperframes` binary exists (``0.8.111``) and answers. **Its render path does not
terminate**: ``hyperframes render`` was observed exceeding 90s and 600s without
completing, twice. That is a real defect in the CLI, recorded in
``docs/P9-HYPERFRAMES-AUDIT.md``.

The provider itself is not broken, though. ``hyperframes_generate`` catches a failed CLI
and falls back to an ffmpeg path, which **does** produce a real 1920x1080 h264 MP4. So
the provider can render; only its preferred mechanism hangs.

This adapter therefore declares a bounded budget (:class:`HyperFramesExecutionConfig`),
passes it through, and records *which path* produced the artifact. It does not pretend
the CLI worked, and it does not lower the provider's own default — the config is an
input the provider already accepts.

No retry loop, no ``while True``, no unbounded sleep. A qualification run must
terminate, or it cannot report anything.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
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

#: The provider's own default is 600s. The adapter declares a *smaller, explicit*
#: budget rather than inheriting an unbounded one — and the CLI is known to exceed
#: it, so the fallback is expected to do the work.
DEFAULT_TIMEOUT_SECONDS = 180

#: Generous headroom over the provider's internal timeout so the adapter's wall clock
#: is never the thing that fires first; a provider that overruns its own budget is a
#: provider failure, not a harness failure.
WALL_CLOCK_HEADROOM = 1.5


@dataclass(frozen=True)
class HyperFramesExecutionConfig:
    """The declared execution contract. Every bound is explicit."""

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    working_directory: Path = field(default_factory=lambda: Path(".").resolve())
    artifact_locator: Path = field(default_factory=lambda: Path(".").resolve() / "hyperframes.mp4")

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"HYPERFRAMES_TIMEOUT_MUST_BE_POSITIVE:{self.timeout_seconds}; an "
                "unbounded render cannot be reported on"
            )

    @property
    def wall_clock_seconds(self) -> float:
        return self.timeout_seconds * WALL_CLOCK_HEADROOM

    def to_dict(self) -> dict[str, str]:
        return {
            "timeout_seconds": str(self.timeout_seconds),
            "working_directory": str(self.working_directory),
            "artifact_locator": str(self.artifact_locator),
        }


def hyperframes_bin() -> str:
    """The declared runtime binary, or "" when absent."""
    try:
        from hevi.providers.hyperframes.provider import detect_hyperframes_bin

        return detect_hyperframes_bin() or ""
    except Exception:
        return ""


def _path_used(records: list[str]) -> str:
    for message in records:
        if "回退" in message or "fallback" in message.lower():
            return "ffmpeg_fallback"
    return "cli" if any("hyperframes cli" in m for m in records) else "unknown"


#: Populated by :func:`_render_capturing_path`; which mechanism produced the artifact.
_last_render_path = "unknown"


async def _render_capturing_path(config: HyperFramesExecutionConfig, prompt: str) -> Path:
    """Render, recording whether the CLI or the ffmpeg fallback actually ran.

    The provider logs which path it took, and that log line is the only honest source
    for it. Reporting ``cli`` after the fallback ran would be a false claim about how
    the artifact came to exist — which is the whole subject of this phase.
    """
    global _last_render_path
    import logging

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Capture()
    logger = logging.getLogger("hevi.providers.hyperframes.provider")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = await _render(config, prompt)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    _last_render_path = _path_used(records)
    return result


async def _render(config: HyperFramesExecutionConfig, prompt: str) -> Path:
    from hevi.providers.hyperframes.compiler import HyperClip, HyperComposition
    from hevi.providers.hyperframes.provider import (
        hyperframes_generate,
        write_workspace,
    )

    work = config.working_directory
    work.mkdir(parents=True, exist_ok=True)
    composition = HyperComposition(
        title="HEVI qualification",
        clips=[HyperClip(start_s=0.0, duration_s=2.0, text="hyperframes", kind="text")],
    )
    write_workspace(composition, work / "composition")

    return Path(
        await hyperframes_generate(
            prompt=prompt,
            output_path=config.artifact_locator,
            # the provider accepts this key; we declare the budget rather than
            # mutating the provider's own default
            config={"timeout_s": float(config.timeout_seconds)},
        )
    )


class HyperframesAdapter:
    """Executes the HyperFrames runtime under a bounded contract. Returns a locator."""

    provider_id = "hyperframes"

    def __init__(self, config: HyperFramesExecutionConfig | None = None) -> None:
        self._config = config

    def config_for(self, request: QualificationRequest) -> HyperFramesExecutionConfig:
        if self._config is not None:
            return self._config
        return HyperFramesExecutionConfig(
            timeout_seconds=int(request.timeout_s) or DEFAULT_TIMEOUT_SECONDS,
            working_directory=Path(request.output_path).parent / "hyperframes_ws",
            artifact_locator=Path(request.output_path),
        )

    def available(self) -> AdapterAvailability:
        if not hyperframes_bin():
            return unavailable("hyperframes_binary_not_found:not on PATH")
        return AdapterAvailability(Availability.AVAILABLE)

    def execute(self, request: QualificationRequest) -> ExecutionResult:
        availability = self.available()
        if not availability.can_run:
            raise RuntimeUnavailable(availability.reason)

        config = self.config_for(request)
        prompt = str(request.params.get("prompt", "a single blue circle"))
        started = time.monotonic()

        global _last_render_path
        _last_render_path = "unknown"
        try:
            asyncio.run(
                asyncio.wait_for(
                    _render_capturing_path(config, prompt),
                    timeout=config.wall_clock_seconds,
                )
            )
        except TimeoutError as exc:
            # Not a failure of the provider's capability: nothing returned, so nothing
            # can be claimed. Distinct from an exit-code failure, which means the
            # runtime answered and declined.
            raise AdapterFailure(
                ExecutionState.BLOCKED_RUNTIME,
                f"RUNTIME_TIMEOUT:{config.timeout_seconds}s declared budget exceeded "
                f"after {time.monotonic() - started:.1f}s",
            ) from exc
        except RuntimeUnavailable:
            raise
        except AdapterFailure:
            raise
        except Exception as exc:
            raise AdapterFailure(
                ExecutionState.FAILED, f"{type(exc).__name__}:{exc}"[:300]
            ) from exc

        check_locator(request, self.provider_id)
        return result_for(
            request,
            {
                "runtime_class": "local_process",
                "binary": hyperframes_bin(),
                "timeout_seconds": str(config.timeout_seconds),
                "wall_clock_s": f"{time.monotonic() - started:.1f}",
                "render_path": _last_render_path,
            },
        )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "HyperFramesExecutionConfig",
    "HyperframesAdapter",
    "hyperframes_bin",
]
