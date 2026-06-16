import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from hevi.providers.registry import register_all_providers
from obase.provider_registry import ProviderRegistry

async def main():
    register_all_providers()
    caller = ProviderRegistry.get("video", "wan_cloud")
    try:
        # Fixed URL and model are now in the monkeypatch in registry.py
        res = await caller(prompt="A red balloon", output_path=Path("out_wan.mp4"))
        print(f"SUCCESS: {res}")
    except Exception:
        import traceback
        traceback.print_exc()

asyncio.run(main())
