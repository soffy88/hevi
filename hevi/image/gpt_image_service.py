"""GPT-Image cloud image service (via Monid) — generate + reference-based edit.

Fills the image gap formerly covered only by ``sdxl_local_service`` (local GPU
SDXL): while the local GPU is unavailable, this service goes through Monid to
OpenAI's GPT-Image endpoints:

* generation — ``openai`` ``/v1/image/gpt-image-2.5-flare`` (fast, cheap)
* edit/compose — ``openai`` ``/v1/image/gpt-image-2.5-sunburst-edit`` (up to 16
  reference images, built to preserve the source subject — the
  character-consistency workflow: lock a character sheet once, then re-pose /
  re-scene it from the same references)

Verified against Monid 2026-10-20: front portrait → side-profile edit kept the
same face, hair, clothing and studio background. Needs ``MONID_API_KEY``.

Reference images are uploaded to Monid sfs (free signed URLs).
"""

from __future__ import annotations

import asyncio
import logging
import urllib.request
from pathlib import Path
from typing import Any

from hevi.audio import monid_client

logger = logging.getLogger(__name__)

_GENERATE_ENDPOINT = "/v1/image/gpt-image-2.5-flare"
_EDIT_ENDPOINT = "/v1/image/gpt-image-2.5-sunburst-edit"


async def _download(url: str, output_path: Path) -> None:
    def _get() -> None:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=180) as resp:
            output_path.write_bytes(resp.read())

    await asyncio.to_thread(_get)


async def _run_image_endpoint(
    endpoint: str, body: dict[str, Any], output_path: Path
) -> dict[str, Any]:
    output, cost = await monid_client.run_endpoint("openai", endpoint, body=body)
    image = output.get("image") or {}
    download_link = image.get("download_link") or output.get("download_link")
    if not download_link:
        raise monid_client.MonidError(
            f"GPT-Image endpoint {endpoint} returned no download link: {str(output)[:300]}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await _download(str(download_link), output_path)
    logger.info("gpt-image %s -> %s (cost=%s)", endpoint, output_path, cost)
    return {"output_path": str(output_path), "cost": cost}


async def gpt_image_generate(
    *,
    prompt: str,
    output_path: Path | str,
    size: str = "1024x1536",
    quality: str = "medium",
    negative_prompt: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Generate one PNG from a text prompt.

    Signature mirrors ``sdxl_local_generate`` so this can be registered as an
    alternative ``image_gen`` backend.
    """
    full_prompt = prompt
    if negative_prompt:
        full_prompt = f"{prompt}\nAvoid: {negative_prompt}"
    return await _run_image_endpoint(
        _GENERATE_ENDPOINT,
        {"prompt": full_prompt, "size": size, "quality": quality},
        Path(output_path),
    )


async def gpt_image_edit(
    *,
    image_paths: list[Path | str],
    prompt: str,
    output_path: Path | str,
    size: str = "1024x1536",
    quality: str = "medium",
    **_: Any,
) -> dict[str, Any]:
    """Compose/edit a PNG from up to 16 reference images (character consistency)."""
    if not image_paths:
        raise monid_client.MonidError("gpt_image_edit requires at least one reference image")
    if len(image_paths) > 16:
        raise monid_client.MonidError("gpt_image_edit accepts at most 16 reference images")
    urls = [
        await monid_client.sfs_upload_file(Path(p), sfs_path=f"hevi-gpt-image/{Path(p).name}")
        for p in image_paths
    ]
    return await _run_image_endpoint(
        _EDIT_ENDPOINT,
        {"images": urls, "prompt": prompt, "size": size, "quality": quality},
        Path(output_path),
    )
