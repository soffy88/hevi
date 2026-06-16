import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from omodul.agentic_longvideo_pipeline import agentic_longvideo_pipeline, LongVideoConfig
from hevi.providers.registry import register_all_providers
from hevi.core.config import settings

async def main():
    register_all_providers()
    cfg = LongVideoConfig(
        topic="A red balloon",
        duration_archetype="1-5min",
        video_provider="wan_cloud",
        audio_provider="vibevoice",
        style="cinematic",
        num_characters=1,
        language="zh"
    )
    try:
        await agentic_longvideo_pipeline(config=cfg)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
