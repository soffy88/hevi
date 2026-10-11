import asyncio
from hevi.studio.veya import produce
from scripts.qualify_autonomous_production import _slots

async def main():
    job = await produce(
        line_id="localization_dub",
        slots=_slots("localization_dub"),
        output_dir="output/om_lines_e2e/localization_dub",
        execute=True,
        publish=False
    )
    print("JOB STATUS:", job.status)
    print("JOB REASON:", job.reason)
    if job.slate:
        print("SLATE STATUS:", job.slate.get("status"))

if __name__ == "__main__":
    asyncio.run(main())
