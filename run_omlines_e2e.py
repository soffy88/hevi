import asyncio
import logging
import json
import os
from pathlib import Path

# Ensure required binaries are on PATH and direct downloads (no proxy)
os.environ["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{os.environ.get('PATH', '')}"
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(k, None)

from hevi.studio.veya import produce
from scripts.qualify_autonomous_production import _slots
from hevi.studio.production_catalog import CANONICAL_LINES
from hevi.layer4_legacy.omlines.oprim_impl import zl

logging.basicConfig(level=logging.INFO)

async def process_line(sem, line, root):
    async with sem:
        out_dir = root / line
        print(f"[{line}] Starting fresh run...")
        try:
            job = await produce(
                line_id=line,
                slots=_slots(line),
                output_dir=str(out_dir),
                execute=True,
                publish=False
            )
            art = job.artifact
            if not art or not Path(art).is_file():
                return {
                    "line": line,
                    "status": "FAILED",
                    "reason": f"no artifact, status={job.status}, reason={job.reason}",
                }
            
            q = zl.qa(art)
            cs_path = str(out_dir / "contact_sheet.jpg")
            zl.contact_sheet(art, cs_path)
            tier = job.production_order.get("fallback") or job.render_runtime
            
            checks = q.get('checks', {})
            has_audio = checks.get('has_audio', False)
            motion_ratio = q.get('motion_ratio', round(1.0 - q.get('static_ratio', 0.0), 3))
            
            return {
                "line": line,
                "status": "SUCCESS",
                "duration": q['duration'],
                "resolution": q['resolution'],
                "audio": has_audio,
                "motion_ratio": motion_ratio,
                "tier": tier,
                "sha256": q['sha256'],
                "path": art,
                "contact_sheet": cs_path,
                "qa_checks": checks,
            }
        except Exception as e:
            return {
                "line": line,
                "status": "ERROR",
                "reason": f"{type(e).__name__}: {e}",
            }

async def main():
    root = Path("output/om_lines_e2e")
    root.mkdir(parents=True, exist_ok=True)
    
    sem = asyncio.Semaphore(2)  # 2 concurrent lines
    tasks = [process_line(sem, line, root) for line in CANONICAL_LINES]
    results = await asyncio.gather(*tasks)
    
    lines_md = []
    for r in results:
        if r["status"] == "SUCCESS":
            lines_md.append(f"- {r['line']}: {r['duration']}s, {r['resolution']}, audio:{r['audio']}, motion_ratio:{r['motion_ratio']:.2f}, tier:{r['tier']}, SHA:{r['sha256']}")
        else:
            lines_md.append(f"- {r['line']}: FAILED ({r.get('reason', '')})")

    content = "# OMLINES E2E Summary\n\n" + "\n".join(lines_md) + "\n\nAll tasks processed.\n"
    with open("OMLINES_DONE.md", "w") as f:
        f.write(content)
    
    # Also dump detailed raw json for reporting
    with open("output/om_lines_e2e/e2e_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print("ALL DONE. Wrote OMLINES_DONE.md and output/om_lines_e2e/e2e_results.json")

if __name__ == "__main__":
    asyncio.run(main())
