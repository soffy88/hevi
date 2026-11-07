"""omodul：剧本 JSON → 场景 TSX → MP4。

CLI: python -m hevi.motioncanvas.omodul.render_script script.json out.mp4 [--keep-job]
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from hevi.motioncanvas.obase.mc_render import MC_HOME, prepare_job, render_job
from hevi.motioncanvas.oskill.script import project_meta, project_ts, to_scene_tsx, total_duration, validate


def build_files(script: dict) -> dict[str, str]:
    s = validate(script)
    return {"src/project.ts": project_ts("main"), "src/project.meta": project_meta(s),
            "src/scenes/main.tsx": to_scene_tsx(s)}


def render_script(script: dict, out_mp4: str | Path, keep_job: bool = False, timeout: int = 300) -> dict:
    files = build_files(script)
    jobs = MC_HOME / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="job-", dir=jobs))
    try:
        prepare_job(job, files)
        res = render_job(job, timeout=timeout)
        out = Path(out_mp4)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(res["file"], out)
        if keep_job:
            (out.with_suffix(".scene.tsx")).write_text(files["src/scenes/main.tsx"], encoding="utf-8")
        return {"mp4": str(out), "size": res["size"], "duration": res["duration"],
                "expected_duration": total_duration(script), "wall": res["wall"], "job": str(job) if keep_job else None}
    finally:
        if not keep_job:
            shutil.rmtree(job, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--keep-job", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)
    res = render_script(json.loads(Path(a.script).read_text(encoding="utf-8")), a.out, a.keep_job, a.timeout)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
