from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any
from hevi.talkcraft.explainer_adapter import segments_from_storyboard

class ArtmotionRenderError(RuntimeError):
    pass

async def render_storyboard_artmotion(
    storyboard_data: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> dict[str, Any]:
    from hevi.layer4_legacy.artmotion.omodul_impl.produce import produce_artmotion

    segments = segments_from_storyboard(storyboard_data)
    if not segments:
        raise ArtmotionRenderError("storyboard has no narration")
        
    style_id = str(config.get("style_id", "ink"))
    grammar_id = str(config.get("grammar_id", "t1_3b1b"))
    aspect_ratio = str(config.get("aspect_ratio", "16:9"))

    result = await asyncio.to_thread(
        produce_artmotion,
        segments=segments,
        output_dir=Path(output_dir),
        style_id=style_id,
        grammar_id=grammar_id,
        aspect_ratio=aspect_ratio,
        lang=str(config.get("language") or "zh"),
    )
    if result["status"] != "succeeded":
        failed = [
            f"{Path(r['video_path']).name}:{g['name']}={g['value']} ({g.get('message','')})"
            for r in result["records"]
            for g in r["gates"]
            if not g["passed"]
        ]
        raise ArtmotionRenderError("artmotion gates failed: " + ", ".join(failed))
        
    paths = {Path(r["video_path"]).stem.rsplit("_", 1)[-1]: r["video_path"] for r in result["records"]}
    
    # explainer production expects both portrait and landscape paths if it required them.
    # To keep it simple we just return the generated one for both, or we can check which one was generated.
    p = list(paths.values())[0]
    return {"portrait_path": p, "landscape_path": p}

