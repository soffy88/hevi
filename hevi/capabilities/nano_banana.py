"""Nano Banana image generation via the official Gemini API (NOT Flow UI).

Registers ``image.nano_banana_generate`` so every product line can call
Google's Nano Banana image models by dotted name (precedent:
``image.gpt_generate`` in ``multimodel.py``, ``video.pixstag_generate`` in
``pixstag.py``). The transport is plain REST over ``urllib`` (stdlib only,
no new dependency, no google-genai SDK required):

    POST https://generativelanguage.googleapis.com/v1beta/interactions
    header: x-goog-api-key: <key from the environment>
    body: {"model": ..., "input": <prompt>,
           "response_format": {"type": "image",
                               "aspect_ratio": "16:9",
                               "image_size": "1K"}}

Shape per the official image-generation guide
(https://ai.google.dev/gemini-api/docs/image-generation, "Model selection"
and "Aspect ratios and image size" sections, fetched 2026-10-25). The
response image is read from ``interaction.output_image.data`` (base64);
a generateContent-style ``candidates[0].content.parts[].inlineData`` shape
is accepted as a defensive fallback. A response with no image data raises
``CapabilityError`` -- never a fake success.

Model ids -- official Gemini API docs, NOT Flow UI labels (fetched
2026-10-25; Flow shows no literal "Nano Banana 2" option, only Pro /
2 Lite / 2.1, and Flow's UI labels are not API documentation):

    Nano Banana 2.1   -> gemini-nano-banana-2.1
        Official image-generation guide: "primary high-efficiency
        workhorse", 1K/2K/4K. This is the default here: Google's
        recommended workhorse, cheapest 1K tier (tied with Lite), and
        the only model documented with the extreme ratios below.
    Nano Banana 2 Lite -> gemini-3.1-flash-lite-image
        Official guide: "fastest and cheapest", "not optimized for
        multiple reference inputs or multi-turn sequential editing".
        Flow's "2 Lite" label matches this product name; the id is from
        the official guide, not from Flow. Pricing page lists only a
        1K equivalent for Lite, so non-1K sizes are refused here
        before any network call.
    Nano Banana 2     -> gemini-3.1-flash-image
        Official guide: "previous-generation high-efficiency workhorse";
        "recommended for all new projects to use Nano Banana 2.1".
        Flow's "2.1" label is NOT this id -- it is the 2.1 row above.
        Kept in the enum only so existing callers can pin it.
    Nano Banana Pro   -> gemini-3-pro-image
        Official model page: "Nano Banana Pro is a sophisticated
        reasoning-driven engine" (https://ai.google.dev/gemini-api/docs/
        models/gemini-3-pro-image). Flow's "Pro" label matches this
        product name; the id is from the official docs. The stable id
        is gemini-3-pro-image; the older gemini-3-pro-image-preview id
        is intentionally NOT accepted (third-party notes report it
        shut down; it is not the documented stable id).
    Nano Banana (original) -> gemini-2.5-flash-image
        Official model page: "Gemini 2.5 Flash Image, also known as
        Nano Banana" (https://ai.google.dev/gemini-api/docs/models/
        gemini-2.5-flash-image); the image-generation guide calls it
        "the legacy pioneer" and recommends migrating to 2 Lite.

Model selection is configurable two ways, in this precedence order:
params["model"] > HEVI_NANO_BANANA_MODEL env > default
(gemini-nano-banana-2.1). An env/param value outside the allowlist above
is refused before any network call.

COST GATE -- READ BEFORE CALLING (this corrects the "free tier" premise):
the official pricing page (https://ai.google.dev/gemini-api/docs/pricing,
fetched 2026-10-25) lists Free Tier = "Not available" for Nano Banana
2.1, Nano Banana 2, and Nano Banana 2 Lite. There is NO free tier for
Gemini API image generation. The Flow manual route that cost 0 points
(balance 420 -> 420 on 2026-10-25) is a consumer-surface (Gemini app /
Flow) allowance with its own billing owner; it is NOT Gemini API free
tier, and a Flow allowance does not make API calls free. Therefore:

* ``allow_paid`` defaults to False, and a call with ``allow_paid``
  False is refused with CapabilityError BEFORE the key is read and
  before any network call. Nothing is billed by accident.
* ``allow_paid=True`` is the caller's explicit, per-call acceptance
  that the key's project will be billed at the Standard-tier rates
  below. There is no env var that silently enables paid calls.
* Per-image USD estimates (Standard tier, official pricing page):
  2.1: 1K $0.0336, 2K $0.0504, 4K $0.113; 2: 1K $0.067, 2K $0.101,
  4K $0.151; Lite: 1K $0.0336. Estimates are approximate: the pricing
  page's 4K figure for 2.1 ($0.113, 3780 tokens) disagrees with the
  image-generation guide's 2.1 size table (2520 tokens at 4K, which
  would be $0.0756); the pricing-page figure is used and flagged
  approximate. Pro and 2.5-flash-image per-image prices were NOT
  verified in this fetch, so their estimates are None (unknown),
  never invented.
* Rate limits / quotas: the pricing page does not publish per-model
  RPM/TPM/RPD numbers for these models (Google directs users to check
  their own project's limits in AI Studio); no rate-limit numbers are
  claimed here. All generated images carry a SynthID watermark per
  the official guide.

Auth: GEMINI_API_KEY first, then GOOGLE_API_KEY (the official REST
example uses $GEMINI_API_KEY in the x-goog-api-key header). The key is
read only from the environment, never has a default value, and is never
written to files, sidecars, logs, or error messages. The sidecar
records the model, prompt, and cost estimate, but never the key.

Chinese text rendering: pass ``chinese_text`` with the exact characters
(e.g. a shop signboard / plaque text such as the Flow-tested plaque).
The effective prompt gains a template block demanding the characters
be rendered exactly, character for character, with correct strokes and
no substitution, paraphrase, omission, or extra characters. Evidence
status, stated honestly: Flow-side manual generation rendered the
plaque text correctly (2026-10-25实测); API-side Chinese rendering has
NOT been verified yet (no key was available at build time) and must be
re-checked once a key is in place. The official guide's own tip is
baked into the template guidance: generate the text first, then ask
for the image with the text; short exact strings render best, long
paragraphs still error. ``seed`` is accepted by the capability
contract but is NOT sent to the API (the documented Interactions REST
shape has no seed field); outputs are therefore not deterministic
across calls, and the sidecar says so.

Flow relation: the Flow manual route stays usable as-is for hand work.
This capability is the API automation route for the same model family;
it does not drive, log into, or scrape the Flow web UI.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

DEFAULT_MODEL = "gemini-nano-banana-2.1"

# Product name -> official Gemini API model id (see module docstring).
MODEL_IDS: dict[str, str] = {
    "nano_banana_2.1": "gemini-nano-banana-2.1",
    "nano_banana_2_lite": "gemini-3.1-flash-lite-image",
    "nano_banana_2": "gemini-3.1-flash-image",
    "nano_banana_pro": "gemini-3-pro-image",
    "nano_banana": "gemini-2.5-flash-image",
}
ALLOWED_MODELS = tuple(MODEL_IDS.values())

ASPECT_RATIOS = (
    "1:1",
    "1:4",
    "1:8",
    "2:3",
    "3:2",
    "3:4",
    "4:1",
    "4:3",
    "4:5",
    "5:4",
    "8:1",
    "9:16",
    "16:9",
    "21:9",
)
# The 10 ratios every Nano Banana API model documents; extreme ratios
# (1:4, 4:1, 1:8, 8:1) are documented for 2.1 and passed through for the
# others -- the server rejects combinations a model does not support.
IMAGE_SIZES = ("1K", "2K", "4K")

# Per-image USD estimates, Standard tier, official pricing page
# (fetched 2026-10-25). None = not verified in this fetch, never guessed.
# 2.1 4K uses the pricing-page figure; see the docstring discrepancy note.
# SINGLE SOURCE: these prices are read from the configured catalogue
# data file (hevi/capabilities/model_catalog_data/models.json) via
# model_catalog.py. The literal below is only a fallback for the case
# where that data file cannot be loaded; it must match the catalogue.
try:
    from hevi.capabilities.model_catalog import per_image_prices as _catalog_prices

    PER_IMAGE_USD: dict[str, dict[str, float | None]] = _catalog_prices()
except Exception:  # pragma: no cover - catalogue file is present in-tree
    PER_IMAGE_USD = {
        "gemini-nano-banana-2.1": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113},
        "gemini-3.1-flash-lite-image": {"1K": 0.0336, "2K": None, "4K": None},
        "gemini-3.1-flash-image": {"1K": 0.067, "2K": 0.101, "4K": 0.151},
        "gemini-3-pro-image": {"1K": None, "2K": None, "4K": None},
        "gemini-2.5-flash-image": {"1K": None, "2K": None, "4K": None},
    }

_COST_NOTE = (
    "Gemini API image generation has NO free tier (official pricing page: "
    "Free Tier = Not available for Nano Banana 2.1 / 2 / 2 Lite). Every call "
    "bills the key's project at Standard-tier rates; allow_paid=True is the "
    "caller's explicit per-call acceptance. Flow manual 0-point use is a "
    "separate consumer-surface allowance, not API free tier."
)

_CHINESE_TEXT_TEMPLATE = (
    "Text rendering requirement: render the following Chinese characters "
    "exactly, character for character, with correct strokes and no "
    "substitution, paraphrase, omission, or extra characters: [{text}]. "
    "If the text belongs on a signboard, plaque, or shop board, paint it "
    "large, legible, and centered on that board in a traditional style, "
    "and keep the rest of the scene unchanged."
)


class NanoBananaError(RuntimeError):
    """Transport / response failure from the Gemini API call."""


def build_effective_prompt(prompt: str, chinese_text: str | None) -> str:
    """Append the exact-characters template when Chinese text is given."""
    prompt = str(prompt)
    if chinese_text is None or str(chinese_text) == "":
        return prompt
    return prompt + "\n" + _CHINESE_TEXT_TEMPLATE.format(text=str(chinese_text))


def resolve_model(param_model: str | None) -> str:
    """params model > HEVI_NANO_BANANA_MODEL env > default; allowlist only."""
    raw = param_model or os.environ.get("HEVI_NANO_BANANA_MODEL") or DEFAULT_MODEL
    model = str(raw).strip()
    if model not in ALLOWED_MODELS:
        raise CapabilityError(
            "image.nano_banana_generate: unknown model "
            f"{model!r}; allowed: {', '.join(ALLOWED_MODELS)} "
            "(set params model or HEVI_NANO_BANANA_MODEL to one of these)"
        )
    return model


def resolve_api_key() -> str:
    """GEMINI_API_KEY first, then GOOGLE_API_KEY; no default, no logging."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    raise CapabilityError(
        "image.nano_banana_generate: no API key in the environment; set "
        "GEMINI_API_KEY (or GOOGLE_API_KEY). The key is never read from "
        "code, files, or call arguments."
    )


def _http_post(url: str, payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    """Single Interactions REST call. Monkeypatched by unit tests."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise NanoBananaError(
            f"Gemini API HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise NanoBananaError(f"Gemini API request failed: {exc}") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise NanoBananaError("Gemini API returned a non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise NanoBananaError("Gemini API returned an unexpected response shape")
    return parsed


def _extract_image_bytes(payload: dict[str, Any]) -> tuple[bytes, str]:
    """Find base64 image data in an Interactions or generateContent reply."""
    candidates: list[dict[str, Any]] = []
    interaction = payload.get("interaction")
    if isinstance(interaction, dict):
        candidates.append(interaction)
    candidates.append(payload)
    for node in candidates:
        image = node.get("output_image")
        if isinstance(image, dict) and image.get("data"):
            data = str(image["data"])
            mime = str(image.get("mime_type") or image.get("mimeType") or "image/png")
            try:
                return base64.b64decode(data, validate=True), mime
            except (binascii.Error, ValueError) as exc:
                raise NanoBananaError("Gemini API returned invalid base64 image data") from exc
        images = node.get("output_images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict) and first.get("data"):
                try:
                    return base64.b64decode(str(first["data"]), validate=True), "image/png"
                except (binascii.Error, ValueError) as exc:
                    raise NanoBananaError("Gemini API returned invalid base64 image data") from exc
    # Defensive fallback: generateContent-style candidates shape.
    raw_candidates = payload.get("candidates")
    if isinstance(raw_candidates, list):
        for cand in raw_candidates:
            content = cand.get("content") if isinstance(cand, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                inline = part.get("inlineData") if isinstance(part, dict) else None
                if isinstance(inline, dict) and inline.get("data"):
                    try:
                        return (
                            base64.b64decode(str(inline["data"]), validate=True),
                            str(inline.get("mimeType") or "image/png"),
                        )
                    except (binascii.Error, ValueError) as exc:
                        raise NanoBananaError("Gemini API returned invalid base64 image data") from exc
    raise NanoBananaError("Gemini API response contained no image data")


def _generate_one(
    *,
    model: str,
    prompt: str,
    aspect_ratio: str,
    image_size: str,
    api_key: str,
    timeout: int = 300,
) -> bytes:
    """One billed Interactions call -> raw image bytes (PNG unless told)."""
    payload: dict[str, Any] = {
        "model": model,
        "input": prompt,
        "response_format": {
            "type": "image",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        },
    }
    reply = _http_post(API_URL, payload, api_key, timeout)
    image_bytes, _mime = _extract_image_bytes(reply)
    return image_bytes


def _render_nano_banana_generate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    # COST GATE FIRST: every Gemini API image call bills (no free tier),
    # so a call that has not explicitly accepted paid billing is refused
    # before the key is read and before any network traffic.
    if not params.get("allow_paid", False):
        raise CapabilityError(
            "image.nano_banana_generate: refused -- Gemini API image "
            "generation has no free tier (official pricing: Free Tier = "
            "Not available), so this call would bill the key's project. "
            "Pass allow_paid=true to explicitly accept paid billing, or "
            "use the Flow manual route for hand work."
        )
    from hevi.capabilities.spend_brake import check_spend_approval

    spend_gate = check_spend_approval(
        params, capability="image.nano_banana_generate"
    )
    model = resolve_model(params.get("model"))
    api_key = resolve_api_key()
    aspect_ratio = str(params.get("aspect_ratio") or (aspect if aspect in ASPECT_RATIOS else "16:9"))
    if aspect_ratio not in ASPECT_RATIOS:
        raise CapabilityError(
            f"image.nano_banana_generate: unsupported aspect_ratio {aspect_ratio!r}"
        )
    image_size = str(params.get("image_size", "1K"))
    if image_size not in IMAGE_SIZES:
        raise CapabilityError(
            f"image.nano_banana_generate: unsupported image_size {image_size!r}"
        )
    if model == "gemini-3.1-flash-lite-image" and image_size != "1K":
        raise CapabilityError(
            "image.nano_banana_generate: Nano Banana 2 Lite "
            "(gemini-3.1-flash-lite-image) publishes only a 1K equivalent "
            "on the official pricing page; use image_size=1K or another model"
        )
    n = int(params.get("n", 1))
    if n < 1 or n > 4:
        raise CapabilityError("image.nano_banana_generate: n must be 1..4")
    prompt = build_effective_prompt(str(params["prompt"]), params.get("chinese_text"))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        blobs = [
            _generate_one(
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                api_key=api_key,
            )
            for _ in range(n)
        ]
    except NanoBananaError as exc:
        raise CapabilityError(f"image.nano_banana_generate: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"image.nano_banana_generate failed: {exc}") from exc

    images: list[dict[str, Any]] = []
    for index, blob in enumerate(blobs, start=1):
        name = "image.png" if n == 1 else f"image_{index}.png"
        path = out_dir / name
        path.write_bytes(blob)
        images.append({"path": str(path), "sha256": compute_sha256(path)})
    first_path = Path(images[0]["path"])

    per_image = PER_IMAGE_USD[model][image_size]
    estimated = round(per_image * n, 6) if per_image is not None else None

    sidecar = out_dir / "nano_banana_sidecar.json"
    sidecar.write_text(
        json.dumps(
            {
                "capability": "image.nano_banana_generate",
                "model": model,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "n": n,
                "prompt": prompt,
                "chinese_text": params.get("chinese_text"),
                "images": images,
                "estimated_cost_usd": estimated,
                "cost_estimate_note": (
                    "Approximate Standard-tier estimate from the official "
                    "pricing page; None means not verified in this fetch. "
                    "Actual billing is per the key's project."
                    if estimated is not None
                    else "Per-image price not verified in this fetch; "
                    "actual billing is per the key's project."
                ),
                "cost_note": _COST_NOTE,
                "seed_note": (
                    "seed is accepted by the capability contract but is "
                    "NOT sent to the API (no seed field in the documented "
                    "Interactions REST shape); outputs are not deterministic."
                ),
                "flow_note": (
                    "Flow manual route stays usable for hand work; this is "
                    "the API automation route for the same model family and "
                    "does not drive the Flow web UI."
                ),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    return CapabilityResult(
        png=str(first_path),
        duration_s=0.0,
        sha256=str(images[0]["sha256"]),
        qa={
            "model": model,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "image_count": n,
            "images": [entry["path"] for entry in images],
            "estimated_cost_usd": estimated,
            "spend_gate": spend_gate,
            "sidecar_json": str(sidecar),
            "note": _COST_NOTE,
        },
    )


def register_nano_banana_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.nano_banana_generate",
            kind="shot",
            aspects=[
                "16:9",
                "9:16",
                "1:1",
                "4:3",
                "3:4",
                "3:2",
                "2:3",
                "4:5",
                "5:4",
                "21:9",
            ],
            params_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Text prompt for the image",
                    },
                    "model": {
                        "type": "string",
                        "enum": list(ALLOWED_MODELS),
                        "description": (
                            "Gemini API model id; default "
                            "gemini-nano-banana-2.1 (Nano Banana 2.1). "
                            "HEVI_NANO_BANANA_MODEL env overrides the "
                            "default when params model is absent."
                        ),
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": list(ASPECT_RATIOS),
                        "description": (
                            "Output aspect ratio; defaults to the "
                            "render aspect when it is a supported ratio, "
                            "else 16:9. Extreme ratios (1:4, 4:1, 1:8, "
                            "8:1) are documented for Nano Banana 2.1."
                        ),
                    },
                    "image_size": {
                        "type": "string",
                        "enum": list(IMAGE_SIZES),
                        "default": "1K",
                        "description": "Output size tier; 1K default (cheapest).",
                    },
                    "n": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 4,
                        "default": 1,
                        "description": (
                            "How many images to generate; each is a "
                            "separate billed API call (Flow x4 parity cap)."
                        ),
                    },
                    "chinese_text": {
                        "type": "string",
                        "description": (
                            "Exact Chinese characters to render in the "
                            "image (e.g. signboard / plaque text). Adds "
                            "an exact-characters template block to the "
                            "prompt; API-side rendering is not yet "
                            "verified (see module docstring)."
                        ),
                    },
                    "allow_paid": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "REQUIRED to be true for any real call: "
                            "Gemini API image generation has no free "
                            "tier, so every call bills the key's "
                            "project. False (default) refuses before "
                            "any network call."
                        ),
                    },
                    "spend_approval": {
                        "type": "object",
                        "description": (
                            "Optional spend-gate block: {storyboard, "
                            "confirmed, smoke_passed, batch_size, "
                            "estimated_unit_cost}. When supplied, the "
                            "spend gate must approve before any key read, "
                            "network call, or GPU work; when absent, "
                            "spending responsibility stays caller-side and "
                            "the result qa carries "
                            "spend_gate_not_consulted=true."
                        ),
                    },
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,  # cloud render; local cost is request + download only
            render=_render_nano_banana_generate,
            description=(
                "Nano Banana text-to-image via the official Gemini API "
                "(Interactions REST, GEMINI_API_KEY / GOOGLE_API_KEY). "
                "Default model gemini-nano-banana-2.1 (Nano Banana 2.1); "
                "16:9 etc. aspect ratios, 1-4 images per call, exact-"
                "Chinese-characters template via chinese_text. PAID ONLY: "
                "no API free tier exists, so allow_paid=true is required "
                "per call; Flow manual use stays available for hand work."
            ),
            line="image",
        )
    )
    return ["image.nano_banana_generate"]
