"""Generate an illustration for a substrate or fragment via SD 1.5."""

from __future__ import annotations

from dataclasses import dataclass

from oprim._logging import log
from oprim.external.clients.sd_client import SdClient
from oprim.external.gpu_lock import GpuLock
from oprim.meta_db import open_meta_db

from oskill.knowledge._context import meta_db_path, stratum_home


@dataclass
class IllustrationResult:
    substrate_id: str
    illustration_asset_id: str
    image_path: str
    sd_prompt: str
    width: int
    height: int
    cost_usd: float = 0.0


async def generate_illustration(
    substrate_id: str,
    fragment_id: str | None = None,
    prompt: str | None = None,
    negative_prompt: str = "ugly, blurry, low quality, watermark, text",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
) -> IllustrationResult:
    """Generate an illustration for a substrate or fragment.

    If prompt is None, auto-generates an SD prompt from the substrate's title
    and first 200 chars of content via LLM. Acquires GpuLock for SD inference.

    Args:
        substrate_id: Target substrate ULID.
        fragment_id: Optional fragment ULID for fragment-level illustration.
        prompt: Explicit SD prompt. If None, auto-generated from content.
        negative_prompt: SD negative prompt.
        width / height: Output image dimensions (SD 1.5 optimum: 512×512).
        steps: Denoising steps (20 is fast; 30+ for higher quality).

    Returns:
        IllustrationResult with path to generated PNG.
    """
    if prompt is None:
        prompt = await _build_sd_prompt(substrate_id, fragment_id)

    log.info(
        "generate_illustration.start",
        substrate_id=substrate_id,
        fragment_id=fragment_id,
        prompt=prompt[:80],
    )

    illus_dir = stratum_home() / "data" / "illustrations"
    illus_dir.mkdir(parents=True, exist_ok=True)

    gpu_lock = GpuLock()
    sd = SdClient()
    try:
        async with gpu_lock.acquire(requester=f"illustration:{substrate_id}"):
            png_bytes = await sd.generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
            )
    finally:
        await sd.close()
        await gpu_lock.close()

    from python_ulid import ULID

    asset_id = str(ULID())
    out_path = illus_dir / f"{asset_id}.png"
    out_path.write_bytes(png_bytes)

    _save_illustration_asset(
        asset_id=asset_id,
        substrate_id=substrate_id,
        fragment_id=fragment_id,
        file_path=str(out_path),
        sd_prompt=prompt,
        width=width,
        height=height,
        byte_size=len(png_bytes),
    )

    log.info(
        "generate_illustration.done",
        substrate_id=substrate_id,
        asset_id=asset_id,
        bytes=len(png_bytes),
    )
    return IllustrationResult(
        substrate_id=substrate_id,
        illustration_asset_id=asset_id,
        image_path=str(out_path),
        sd_prompt=prompt,
        width=width,
        height=height,
        cost_usd=0.0,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _build_sd_prompt(substrate_id: str, fragment_id: str | None) -> str:
    """Use LLM to generate an SD prompt from substrate title + snippet."""
    title, snippet = _fetch_title_snippet(substrate_id, fragment_id)
    base = f"Illustration for: {title}. {snippet[:200]}"
    try:
        from oprim.llm import llm_call

        resp = llm_call(
            prompt=(
                f"Write a concise Stable Diffusion image prompt (50 words max) "
                f"that visually represents the following content. "
                f"No quotes, no explanation, just the prompt:\n\n{base}"
            ),
            temperature=0.5,
            max_tokens=80,
        )
        return resp.text.strip()
    except Exception as exc:
        log.warning("generate_illustration.llm_prompt_failed", error=str(exc))
        return f"Digital illustration, {title[:60]}, professional artwork"


def _fetch_title_snippet(substrate_id: str, fragment_id: str | None) -> tuple[str, str]:
    db_path = meta_db_path()
    if not db_path.exists():
        return substrate_id, ""
    try:
        db = open_meta_db(db_path)
        rows = db.fetchall(
            "SELECT title FROM substrates WHERE id = ?",
            [substrate_id],
        )
        title = rows[0][0] if rows and rows[0][0] else substrate_id

        if fragment_id:
            frows = db.fetchall(
                "SELECT content FROM derivative WHERE id = ?",
                [fragment_id],
            )
            snippet = (frows[0][0] or "")[:200] if frows else ""
        else:
            drows = db.fetchall(
                "SELECT content FROM derivative WHERE substrate_id = ? AND kind = 'plaintext' LIMIT 1",
                [substrate_id],
            )
            snippet = (drows[0][0] or "")[:200] if drows else ""
        db.close()
        return title, snippet
    except Exception as exc:
        log.warning("generate_illustration.fetch_title_snippet_failed", error=str(exc))
        return substrate_id, ""


def _save_illustration_asset(
    asset_id: str,
    substrate_id: str,
    fragment_id: str | None,
    file_path: str,
    sd_prompt: str,
    width: int,
    height: int,
    byte_size: int,
) -> None:
    db_path = meta_db_path()
    if not db_path.exists():
        return
    try:
        db = open_meta_db(db_path)
        db.execute(
            """
            INSERT INTO illustration_assets
                (id, substrate_id, fragment_id, file_path, sd_prompt, width, height, byte_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [asset_id, substrate_id, fragment_id, file_path, sd_prompt, width, height, byte_size],
        )
        db.close()
    except Exception as exc:
        log.warning("generate_illustration.save_asset_failed", error=str(exc))
