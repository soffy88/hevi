import asyncio
import logging
logging.basicConfig(level=logging.INFO)
from hevi.studio.veya import produce
from scripts.qualify_autonomous_production import _slots

async def main():
    job = await produce(
        line_id="talking_head",
        slots=_slots("talking_head"),
        output_dir="output/om_lines_e2e/talking_head",
        execute=True,
        publish=False
    )
    print("JOB STATUS:", job.status)
    print("JOB REASON:", job.reason)
    if job.slate:
        print("SLATE STATUS:", job.slate.get("status"))

if __name__ == "__main__":
    asyncio.run(main())
