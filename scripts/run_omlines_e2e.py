import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
        print(f"[{line}] Starting production...")
        try:
            job = await produce(
                line_id=line,
                slots=_slots(line),
                output_dir=str(out_dir),
                execute=True,
                publish=False,
            )
            art = job.artifact
            if not art or not Path(art).is_file():
                return {
                    "line": line,
                    "status": "FAIL",
                    "reason": f"no artifact, job_status={job.status}, reason={job.reason}",
                    "checks": {},
                }

            q = zl.qa(art)
            cs_path = str(out_dir / "contact_sheet.jpg")
            zl.contact_sheet(art, cs_path)
            tier = job.production_order.get("fallback") or job.render_runtime

            checks = q.get("checks", {})
            has_audio = checks.get("has_audio", False)
            motion_ratio = q.get("motion_ratio", round(1.0 - q.get("static_ratio", 0.0), 3))

            # Quality gate: all measured physical QA checks must pass to be SUCCESS
            passed = bool(q.get("pass", False)) and all(checks.values())
            status = "SUCCESS" if passed else "FAIL"

            return {
                "line": line,
                "status": status,
                "duration": q["duration"],
                "resolution": q["resolution"],
                "audio": has_audio,
                "motion_ratio": motion_ratio,
                "tier": tier,
                "sha256": q["sha256"],
                "path": art,
                "contact_sheet": cs_path,
                "qa_checks": checks,
                "metrics": {
                    "motion_mean": q.get("motion_mean"),
                    "motion_ratio": motion_ratio,
                    "static_ratio": q.get("static_ratio"),
                    "black_ratio": q.get("black_ratio"),
                    "dark_textcard_ratio": q.get("dark_textcard_ratio"),
                },
            }
        except Exception as e:
            return {
                "line": line,
                "status": "FAIL",
                "reason": f"{type(e).__name__}: {e}",
                "checks": {},
            }


async def main():
    root = Path("output/om_lines_e2e")
    root.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(2)  # 2 concurrent lines for bounded CPU usage
    tasks = [process_line(sem, line, root) for line in CANONICAL_LINES]
    results = await asyncio.gather(*tasks)

    # Dump detailed raw json for auditing
    e2e_json_path = root / "e2e_results.json"
    with open(e2e_json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    all_passed = all(r["status"] == "SUCCESS" for r in results)
    print(f"E2E Complete. Results saved to {e2e_json_path}. All passed: {all_passed}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
