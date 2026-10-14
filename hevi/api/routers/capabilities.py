"""HTTP adapter for the shared Hevi capability registry."""
from __future__ import annotations

import hashlib
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from hevi.capabilities.registry import CapabilityError
from hevi.capabilities.registry import get as get_capability
from hevi.capabilities.registry import list as list_capabilities

router = APIRouter(tags=["capabilities"])
_PREVIEW_LOCK = threading.Lock()
REPO_ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = REPO_ROOT / ".tmp" / "capability-previews"


class CapabilityPreviewRequest(BaseModel):
    topic: str = Field(default="小狐狸学会轮流", min_length=2, max_length=120)
    aspect: Literal["16:9", "9:16"] = "16:9"
    style_id: Literal["1", "8", "10", "17"] = "17"
    hand_preset: Literal["navy", "pen-only"] = "navy"
    seed: int = 0


@router.get("/capabilities")
def list_capability_contracts() -> dict:
    """Expose the same registered capability catalog used by product lines."""
    import hevi.capabilities.handdraw  # noqa: F401 - import registers the capabilities

    return {
        "items": [
            {
                "name": cap.name,
                "kind": cap.kind,
                "aspects": list(cap.aspects),
                "params_schema": cap.params_schema,
                "cpu_cost_hint": cap.cpu_cost_hint,
                "description": cap.description,
            }
            for cap in list_capabilities()
        ]
    }


@router.post("/capabilities/{name}/preview")
def render_capability_preview(name: str, body: CapabilityPreviewRequest) -> FileResponse:
    """Render a real 3-second MP4 using the shared capability implementation."""
    if name != "handdraw.full":
        raise HTTPException(
            status_code=422,
            detail="Only video capability handdraw.full provides MP4 previews.",
        )
    try:
        import hevi.capabilities.handdraw  # noqa: F401 - ensure registration

        capability = get_capability(name)
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(
            f"{body.topic}|{body.aspect}|{body.style_id}|{body.hand_preset}|{body.seed}".encode()
        ).hexdigest()[:16]
        # Per-request folder avoids stale manifests; all intermediates stay in .tmp.
        with _PREVIEW_LOCK:
            out_dir = Path(tempfile.mkdtemp(prefix=f"{key}-", dir=TEMP_ROOT))
            result = capability.render(
                {
                    "topic": body.topic,
                    "aspect": body.aspect,
                    "style_id": body.style_id,
                    "hand_preset": body.hand_preset,
                },
                out_dir,
                duration=3.0,
                aspect=body.aspect,
                seed=body.seed,
            )
        if result.mp4 is None or not result.mp4.is_file() or result.duration is None:
            raise CapabilityError("preview renderer returned no MP4")
        if abs(float(result.duration) - 3.0) > 0.1:
            raise CapabilityError(f"preview duration is {result.duration}, expected 3 seconds")
        return FileResponse(
            str(result.mp4),
            media_type="video/mp4",
            filename="handdraw-preview.mp4",
            headers={
                "X-Capability-Duration": f"{float(result.duration):.3f}",
                "X-Capability-SHA256": str(result.sha256 or ""),
                "X-Capability-Name": name,
            },
        )
    except HTTPException:
        raise
    except CapabilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Capability preview failed: {type(exc).__name__}: {exc}",
        ) from exc
