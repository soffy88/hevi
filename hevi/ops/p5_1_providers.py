"""HEVI P5.1 — native video understanding provider.

Architecture redlines honoured here:

* **No second provider registry.** The implementation registers into the
  existing canonical ``obase.ProviderRegistry`` singleton, under the
  ``video_understanding`` generic category plus a typed ``ProviderSpec`` that
  declares the ``VIDEO_UNDERSTANDING`` / ``NATIVE_VIDEO_INPUT`` capabilities.
  Provider authority stays exactly where P0-P5 already put it.
* **Capability-aware selection, no silent fallback.** If nothing declares
  ``VIDEO_UNDERSTANDING`` + ``NATIVE_VIDEO_INPUT``, selection returns a blocked
  result (``BLOCKED_BY_PROVIDER``). A frame-only reviewer is never substituted
  for a native video reviewer.
* **Cost honesty.** Cost is ``None`` (UNKNOWN) when the provider does not
  report it. It is never coerced to ``0.0``.

§9 note: this repository contains no Antigravity CLI/Gemini adapter (audited —
DashScope returns ``Arrearage``, TeamoRouter returns ``insufficient_balance``,
the OpenCode gateway requires a paid subscription, and the local Ollama
Qwen2.5-VL silently ignores a ``videos`` field, verified by an identical
prompt-token count with and without the video and by the model stating no video
was attached). The conditional Antigravity path is therefore unavailable, and
the ``VideoUnderstandingProvider`` contract is implemented against the existing
provider authority instead. Antigravity would only ever be an implementation of
this contract, never an authority.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from obase.provider_registry import ProviderRegistry
from obase.provider_routing import ModelSpec, ProtocolFamily, ProviderSpec

from hevi.ops.p5_1_types import NATIVE_VIDEO_INPUT, VIDEO_UNDERSTANDING

#: Generic registry category for video-understanding providers.
VIDEO_UNDERSTANDING_CATEGORY = "video_understanding"

#: fal.ai already serves HEVI video generation through this key, so video
#: understanding joins the *existing* fal provider family rather than creating
#: a new vendor integration surface.
FAL_RUN_BASE = "https://fal.run"
DEFAULT_VIDEO_MODEL = "fal-ai/video-understanding"

_REGISTERED = False


# ── Errors ───────────────────────────────────────────────────────────────


class VideoUnderstandingUnavailable(RuntimeError):
    """No registered provider can accept native video input."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class VideoUnderstandingRequestError(ValueError):
    """A review request was malformed before it reached any provider."""


class VideoUnderstandingCallError(RuntimeError):
    """A native-video review call failed at the provider edge."""

    def __init__(self, reason: str, *, status_code: int = 0) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)

    @property
    def is_retryable(self) -> bool:
        """Transient provider conditions worth one more attempt.

        A quota/credit hold can clear on its own; a malformed request or a
        refused credential will not, and retrying those only burns time.
        """
        if self.status_code in (408, 425, 429, 500, 502, 503, 504):
            return True
        return self.status_code in (402, 403) and any(
            token in self.reason
            for token in ("TOP_UP", "quota", "rate", "temporarily", "overloaded")
        )


# ── Provider contract (§6) ────────────────────────────────────────────────


@dataclass
class VideoReviewRequest:
    """Input to a ``VideoUnderstandingProvider``.

    The provider receives the *video itself* plus optional auxiliary context.
    Auxiliary inputs (transcript, timeline, shot metadata) may support the
    review, but they never substitute for native video input.
    """

    video_path: str
    prompt: str
    transcript: str = ""
    content_profile: str = ""
    target_audience: str = ""
    visual_beat_summary: str = ""
    shot_plan_summary: str = ""
    max_output_tokens: int = 2048
    timeout_s: float = 240.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoReviewResponse:
    """Raw provider output. ``cost_usd is None`` means UNKNOWN, never zero."""

    text: str = ""
    provider: str = ""
    model: str = ""
    latency_s: float = 0.0
    cost_usd: float | None = None
    input_bytes: int = 0
    native_video_bytes_sent: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class VideoUnderstandingProvider:
    """A provider that accepts a real video and returns editorial observations."""

    provider_id: str = ""
    model_id: str = ""
    capabilities: frozenset[str] = frozenset()
    supports_native_video: bool = False

    async def review_video(self, request: VideoReviewRequest) -> VideoReviewResponse:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "capabilities": sorted(self.capabilities),
            "supports_native_video": self.supports_native_video,
        }


# ── fal.ai native video understanding implementation ─────────────────────


class FalVideoUnderstandingProvider(VideoUnderstandingProvider):
    """Native video understanding via fal.ai.

    The whole ``.mp4`` is uploaded as a ``video_url`` data URI. No frame
    extraction, no contact sheet, no ASR substitution.
    """

    provider_id = "fal_video_understanding"
    supports_native_video = True

    def __init__(self, model_id: str = DEFAULT_VIDEO_MODEL, api_key: str = "") -> None:
        self.model_id = model_id
        self._api_key = api_key or os.getenv("FAL_API_KEY", "")
        self.capabilities = frozenset({VIDEO_UNDERSTANDING, NATIVE_VIDEO_INPUT})

    def _key(self) -> str:
        key = self._api_key or os.getenv("FAL_API_KEY", "")
        if not key:
            raise VideoUnderstandingUnavailable("FAL_API_KEY missing")
        return key

    async def review_video(self, request: VideoReviewRequest) -> VideoReviewResponse:
        import httpx

        video = Path(request.video_path)
        if not video.is_file():
            raise VideoUnderstandingCallError(f"video not found: {video}")

        payload_bytes = video.read_bytes()
        encoded = base64.b64encode(payload_bytes).decode("ascii")
        video_uri = f"data:video/mp4;base64,{encoded}"

        body: dict[str, Any] = {
            "video_url": video_uri,
            "prompt": request.prompt,
        }
        body.update(
            {
                key: value
                for key, value in (
                    ("transcript", request.transcript),
                    ("content_profile", request.content_profile),
                    ("target_audience", request.target_audience),
                    ("visual_beat_summary", request.visual_beat_summary),
                    ("shot_plan_summary", request.shot_plan_summary),
                )
                if value
            }
        )

        url = f"{FAL_RUN_BASE}/{self.model_id}"
        headers = {"Authorization": f"Key {self._key()}", "Content-Type": "application/json"}

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_s) as client:
                response = await client.post(url, headers=headers, json=body)
        except Exception as exc:  # network/transport failure at the provider edge
            raise VideoUnderstandingCallError(f"{type(exc).__name__}: {exc}") from exc

        latency = time.monotonic() - started
        if response.status_code >= 400:
            raise VideoUnderstandingCallError(
                f"provider returned {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )

        try:
            raw = response.json()
        except json.JSONDecodeError as exc:
            raise VideoUnderstandingCallError("provider returned non-JSON body") from exc

        text = raw.get("output") or raw.get("output_text") or ""
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)

        return VideoReviewResponse(
            text=text,
            provider=self.provider_id,
            model=self.model_id,
            latency_s=latency,
            cost_usd=raw.get("cost_usd") if isinstance(raw, dict) else None,
            input_bytes=len(json.dumps(body).encode()),
            native_video_bytes_sent=len(payload_bytes),
            raw=raw if isinstance(raw, dict) else {"output": text},
        )


# ── Registration into the EXISTING registry (§6, §8) ──────────────────────


def register_video_understanding_providers(force: bool = False) -> list[str]:
    """Register P5.1 video-understanding providers into the canonical registry.

    Idempotent. Returns the list of registered provider ids.
    """
    global _REGISTERED
    if _REGISTERED and not force:
        return [spec.name for spec in discover_video_understanding_providers()]

    registry = ProviderRegistry.get()
    provider = FalVideoUnderstandingProvider()
    registry.register_generic(
        VIDEO_UNDERSTANDING_CATEGORY, provider.provider_id, provider, replace=True
    )
    spec = ProviderSpec(
        name=provider.provider_id,
        models=(
            ModelSpec(
                name=provider.model_id,
                provider=provider.provider_id,
                capabilities=frozenset({VIDEO_UNDERSTANDING, NATIVE_VIDEO_INPUT}),
                supports_streaming=False,
                supports_tools=False,
                metadata={
                    "accepts": "VIDEO",
                    "input_modes": ["video/mp4", "video/webm", "video/quicktime"],
                    "endpoint": f"{FAL_RUN_BASE}/{provider.model_id}",
                    "credential_ref": "FAL_API_KEY",
                    "family": "fal",
                },
            ),
        ),
        capabilities=frozenset({VIDEO_UNDERSTANDING, NATIVE_VIDEO_INPUT}),
        priority=100,
        enabled=True,
        credential_ref="FAL_API_KEY",
        version="1",
        available=bool(os.getenv("FAL_API_KEY", "")),
        unavailable_reason=None if os.getenv("FAL_API_KEY") else "FAL_API_KEY missing",
        protocol_family=ProtocolFamily.NATIVE,
        metadata={
            "category": VIDEO_UNDERSTANDING_CATEGORY,
            "native_video": True,
            "frame_extraction_fallback": False,
        },
    )
    registry.register_spec(spec, replace=True)
    _REGISTERED = True
    return [provider.provider_id]


def _all_specs() -> list[ProviderSpec]:
    try:
        return list(ProviderRegistry.get().list_specs())
    except Exception:  # registry unavailable in a stripped environment
        return []


def discover_video_understanding_providers(
    *, require_native: bool = True
) -> list[ProviderSpec]:
    """Capability-aware discovery over the *existing* provider registry.

    A provider qualifies only when its spec advertises ``VIDEO_UNDERSTANDING``
    and — when ``require_native`` — ``NATIVE_VIDEO_INPUT``. A provider that
    only accepts frames is not a video-understanding provider.
    """
    required = {VIDEO_UNDERSTANDING}
    if require_native:
        required.add(NATIVE_VIDEO_INPUT)
    out: list[ProviderSpec] = []
    for spec in _all_specs():
        if not spec.enabled or not spec.available:
            continue
        if required.issubset(spec.capabilities):
            out.append(spec)
    out.sort(key=lambda s: (-s.priority, s.name))
    return out


@dataclass
class ProviderSelection:
    """Result of capability-aware provider selection."""

    provider_id: str = ""
    model_id: str = ""
    reason: str = ""
    blocked: bool = False
    considered: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_video_understanding_provider(
    preferred: str | None = None,
) -> ProviderSelection:
    """Select a native-video-capable provider, or report a clean block.

    Never falls back to a frame-only reviewer. Never silently degrades.
    """
    if preferred:
        register_video_understanding_providers()
        specs = {s.name: s for s in _all_specs()}
        spec = specs.get(preferred)
        if spec is None:
            return ProviderSelection(
                blocked=True,
                reason=f"PROVIDER_NOT_REGISTERED:{preferred}",
                considered=sorted(specs),
            )
        if not spec.enabled or not spec.available:
            return ProviderSelection(
                blocked=True,
                reason=f"PROVIDER_UNAVAILABLE:{preferred}",
                rejected={preferred: spec.unavailable_reason or "unavailable"},
            )
        missing = {VIDEO_UNDERSTANDING, NATIVE_VIDEO_INPUT} - set(spec.capabilities)
        if missing:
            return ProviderSelection(
                blocked=True,
                reason="PROVIDER_MISSING_CAPABILITY:" + ",".join(sorted(missing)),
                rejected={preferred: "missing " + ",".join(sorted(missing))},
            )
        model = spec.models[0].name if spec.models else ""
        return ProviderSelection(provider_id=spec.name, model_id=model, reason="PREFERRED")

    register_video_understanding_providers()
    candidates = discover_video_understanding_providers()
    if not candidates:
        return ProviderSelection(
            blocked=True,
            reason="BLOCKED_BY_PROVIDER:no native-video provider declares "
            "VIDEO_UNDERSTANDING+NATIVE_VIDEO_INPUT",
        )
    spec = candidates[0]
    model = spec.models[0].name if spec.models else ""
    return ProviderSelection(
        provider_id=spec.name,
        model_id=model,
        reason="CAPABILITY_MATCH",
        considered=[s.name for s in candidates],
    )


def get_provider(provider_id: str) -> VideoUnderstandingProvider:
    """Fetch a registered native-video provider instance from the registry."""
    register_video_understanding_providers()
    caller = ProviderRegistry.get().generic(VIDEO_UNDERSTANDING_CATEGORY, provider_id)
    if not isinstance(caller, VideoUnderstandingProvider):
        raise VideoUnderstandingUnavailable(
            f"{provider_id} is not a VideoUnderstandingProvider"
        )
    if NATIVE_VIDEO_INPUT not in caller.capabilities:
        # Fail closed rather than degrading to a frame-only reviewer.
        raise VideoUnderstandingUnavailable(
            f"{provider_id} does not declare {NATIVE_VIDEO_INPUT}"
        )
    return caller


# ── Native video probe (§7, adversarial A1) ───────────────────────────────

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def strip_code_fence(text: str) -> str:
    """Reviewers often wrap JSON in a markdown fence. Strip it, don't guess."""
    return _FENCE.sub("", text or "").strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of the first complete JSON object from raw text."""
    cleaned = strip_code_fence(text)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(cleaned[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = cleaned.find("{", start + 1)
    return None


def _ffmpeg_binary() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def build_probe_video(path: Path, *, colors: tuple[str, ...] = ("blue", "orange")) -> bool:
    """Build a real probe clip whose colour changes are time-stamped.

    A reviewer that only ever saw extracted frames, metadata or a contact sheet
    cannot reliably recover both the ordered colour sequence *and* the second at
    which each change happens.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    segment = 2
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, color in enumerate(colors):
        inputs.extend(["-f", "lavfi", "-i", f"color=c={color}:s=320x180:d={segment}"])
        labels.append(f"[{index}:v]")
    filters.append(
        "".join(labels) + f"concat=n={len(colors)}:v=1:a=0[v]"
        if len(colors) > 1
        else f"{labels[0]}null[v]"
    )
    cmd = [
        _ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and path.is_file() and path.stat().st_size > 0


def probe_duration_s(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                os.getenv("FFPROBE_BIN", "ffprobe"), "-v", "error",
                "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
            ],
            capture_output=True, timeout=60, check=False,
        )
        return float(result.stdout.decode().strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


@dataclass
class NativeVideoProbeResult:
    """Qualification evidence that a provider truly consumes video."""

    provider_id: str = ""
    model_id: str = ""
    native_video_input: bool = False
    video_bytes_sent: int = 0
    expected_sequence: list[str] = field(default_factory=list)
    reported_sequence: list[str] = field(default_factory=list)
    expected_change_seconds: list[int] = field(default_factory=list)
    reported_change_seconds: list[float] = field(default_factory=list)
    latency_s: float = 0.0
    cost_usd: float | None = None
    reason: str = ""
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROBE_PROMPT = (
    "Watch the entire clip as a video. Its background is one flat colour, then it "
    "switches to a different flat colour. Report the background colours in the order "
    "they appear and the second at which each change happens. Answer as JSON only: "
    '{"colors": ["..."], "change_seconds": [0.0, ...]}'
)


async def probe_native_video_input(
    provider_id: str | None = None, *, workdir: Path | None = None
) -> NativeVideoProbeResult:
    """Prove a qualification provider genuinely accepts video input.

    Sends a real ``.mp4`` with time-coded content and requires the provider to
    recover both the ordered colour sequence and the change timestamps. A
    frame-only or metadata-only reviewer fails this probe and is blocked.
    """
    selection = select_video_understanding_provider(provider_id)
    if selection.blocked:
        return NativeVideoProbeResult(
            provider_id=provider_id or "",
            native_video_input=False,
            blocked_reason=selection.reason,
            reason="BLOCKED_BY_PROVIDER",
        )

    workdir = workdir or Path("/tmp/hevi_p5_1_probe")
    video = workdir / "native_probe.mp4"
    colors = ("blue", "orange", "white")
    if not build_probe_video(video, colors=colors):
        return NativeVideoProbeResult(
            provider_id=selection.provider_id,
            model_id=selection.model_id,
            native_video_input=False,
            blocked_reason="PROBE_VIDEO_BUILD_FAILED",
            reason="could not build the probe video",
        )

    try:
        provider = get_provider(selection.provider_id)
        response = await provider.review_video(
            VideoReviewRequest(video_path=str(video), prompt=_PROBE_PROMPT, timeout_s=240.0)
        )
    except VideoUnderstandingUnavailable as exc:
        return NativeVideoProbeResult(
            provider_id=selection.provider_id, model_id=selection.model_id,
            native_video_input=False, blocked_reason=str(exc.reason),
            reason="BLOCKED_BY_PROVIDER",
        )
    except VideoUnderstandingCallError as exc:
        return NativeVideoProbeResult(
            provider_id=selection.provider_id, model_id=selection.model_id,
            native_video_input=False, blocked_reason=exc.reason, reason="PROVIDER_CALL_FAILED",
        )

    payload = extract_json_object(response.text) or {}
    reported = [str(c).strip().lower() for c in (payload.get("colors") or [])]
    seconds = [float(s) for s in (payload.get("change_seconds") or []) if _is_number(s)]
    expected = list(colors)

    sequence_ok = _sequence_matches(expected, reported)
    timing_ok = len(seconds) >= 2 and all(
        abs(seconds[i] - i * 2) <= 1.2 for i in range(min(2, len(seconds)))
    )
    native = bool(sequence_ok and timing_ok)

    reason = (
        "NATIVE_VIDEO_CONFIRMED"
        if native
        else f"NOT_NATIVE:sequence_ok={sequence_ok},timing_ok={timing_ok}"
    )
    return NativeVideoProbeResult(
        provider_id=selection.provider_id,
        model_id=response.model or selection.model_id,
        native_video_input=native,
        video_bytes_sent=response.native_video_bytes_sent,
        expected_sequence=expected,
        reported_sequence=reported,
        expected_change_seconds=[i * 2 for i in range(len(expected))],
        reported_change_seconds=seconds,
        latency_s=response.latency_s,
        cost_usd=response.cost_usd,
        reason=reason,
    )


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _sequence_matches(expected: list[str], reported: list[str]) -> bool:
    """Accept the reported colours in order, tolerating a trailing description."""
    if not reported:
        return False
    reported = [c for c in reported if c]
    if len(reported) < len(expected):
        return False
    head = reported[: len(expected)]
    for want, got in zip(expected, head, strict=True):
        if want in got or got in want:
            continue
        return False
    return True


__all__ = [
    "DEFAULT_VIDEO_MODEL",
    "FAL_RUN_BASE",
    "VIDEO_UNDERSTANDING_CATEGORY",
    "FalVideoUnderstandingProvider",
    "NativeVideoProbeResult",
    "ProviderSelection",
    "VideoReviewRequest",
    "VideoReviewResponse",
    "VideoUnderstandingCallError",
    "VideoUnderstandingProvider",
    "VideoUnderstandingRequestError",
    "VideoUnderstandingUnavailable",
    "build_probe_video",
    "discover_video_understanding_providers",
    "extract_json_object",
    "get_provider",
    "probe_native_video_input",
    "register_video_understanding_providers",
    "select_video_understanding_provider",
    "strip_code_fence",
]
