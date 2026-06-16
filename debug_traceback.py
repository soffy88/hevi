import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
from hevi.providers.registry import register_all_providers

async def main():
    register_all_providers()
    try:
        # Simulate what TaskService does
        config_json = {"estimated_usd": 7.2, "credits_reserved": 720}
        await orchestrate_longvideo(
            topic="A red balloon",
            duration_archetype="1-5min",
            video_provider="wan_cloud",
            audio_provider="ltx2_native",
            **config_json
        )
    except Exception:
        import traceback
        traceback.print_exc()

asyncio.run(main())
