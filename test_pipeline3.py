import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
from hevi.providers.registry import register_all_providers
from hevi.core.config import settings

async def main():
    register_all_providers()
    try:
        await orchestrate_longvideo(
            topic="A red balloon",
            duration_archetype="1-5min",
            video_provider="wan_cloud",
            audio_provider="ltx2_native",
            output_dir=Path("output/test_pipeline3")
        )
        print("SUCCESS")
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
