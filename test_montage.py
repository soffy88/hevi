import asyncio
from hevi.studio.veya import produce
from scripts.qualify_autonomous_production import _slots

async def main():
    job = await produce(
        line_id="documentary_montage",
        slots=_slots("documentary_montage"),
        output_dir="output/om_lines_e2e/documentary_montage",
        execute=True,
        publish=False
    )
    print("JOB STATUS:", job.status)
    print("JOB REASON:", job.reason)

if __name__ == "__main__":
    asyncio.run(main())
