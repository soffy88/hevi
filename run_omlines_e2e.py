import asyncio
import logging
import json
from pathlib import Path
from hevi.studio.veya import produce
from scripts.qualify_autonomous_production import _slots
from hevi.studio.production_catalog import CANONICAL_LINES
from hevi.layer4_legacy.omlines.oprim_impl import zl

logging.basicConfig(level=logging.INFO)

async def process_line(sem, line, root):
    async with sem:
        out_dir = root / line
        if (out_dir / "contact_sheet.jpg").is_file():
            # Already succeeded! We just need to read its record if it has one, or evaluate it again.
            print(f"[{line}] Skipping, already completed.")
            # find the mp4
            mp4s = list(out_dir.glob("*.mp4"))
            if mp4s:
                art = str(mp4s[0])
                q = zl.qa(art)
                checks = q.get('checks', {})
                return f"- {line}: {q['duration']}s, {q['resolution']}, audio:{checks.get('has_audio', False)}, motion_ratio:{checks.get('motion_ratio', 0):.2f}, tier:cached, SHA:{q['sha256']}"
            
        print(f"[{line}] Starting...")
        try:
            job = await produce(
                line_id=line,
                slots=_slots(line),
                output_dir=str(root / line),
                execute=True,
                publish=False
            )
            art = job.artifact
            if not art or not Path(art).is_file():
                return f"- {line}: FAILED (no artifact, status={job.status}, reason={job.reason})"
            
            q = zl.qa(art)
            zl.contact_sheet(art, str(root / line / "contact_sheet.jpg"))
            tier = job.production_order.get("fallback") or job.render_runtime
            
            checks = q.get('checks', {})
            has_audio = checks.get('has_audio', False)
            motion_ratio = checks.get('motion_ratio', 0)
            
            return f"- {line}: {q['duration']}s, {q['resolution']}, audio:{has_audio}, motion_ratio:{motion_ratio:.2f}, tier:{tier}, SHA:{q['sha256']}"
        except Exception as e:
            return f"- {line}: ERROR ({type(e).__name__}: {e})"

async def main():
    root = Path("output/om_lines_e2e")
    root.mkdir(parents=True, exist_ok=True)
    
    sem = asyncio.Semaphore(2)  # Max 2 concurrent lines
    tasks = [process_line(sem, line, root) for line in CANONICAL_LINES]
    results = await asyncio.gather(*tasks)
    
    with open("OMLINES_DONE.md", "w") as f:
        f.write("# OMLINES E2E Summary\n\n")
        f.write("\n".join(results))
        f.write("\n\nAll tasks processed.\n")
    print("ALL DONE. Wrote OMLINES_DONE.md")

if __name__ == "__main__":
    asyncio.run(main())
