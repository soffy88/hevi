"""obase：Motion Canvas 无头渲染（vite dev server + 全量 Chromium 点 Render + @motion-canvas/ffmpeg 出 MP4）。

Node 工程在 HEVI_MC_HOME（默认 /data/soffy/projects/hevi/hevi-motioncanvas），其 node_modules 软链复用
_refs/motion-canvas-demo（MIT 依赖，约 301M，不重复安装）。每次渲染建独立 job 目录，可并发。
"""
from __future__ import annotations

import glob
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

MC_HOME = Path(os.environ.get("HEVI_MC_HOME", "/data/soffy/projects/hevi/hevi-motioncanvas"))

VITE_CONFIG = """import {defineConfig} from 'vite';
import motionCanvas from '@motion-canvas/vite-plugin';
import ffmpeg from '@motion-canvas/ffmpeg';

export default defineConfig({
  cacheDir: '.vite',
  server: {fs: {strict: false}},
  plugins: [motionCanvas(), ffmpeg()],
});
"""
TSCONFIG = '{\n  "extends": "@motion-canvas/2d/tsconfig.project.json",\n  "include": ["src"]\n}\n'
PACKAGE = '{\n  "name": "hevi-mc-job",\n  "private": true\n}\n'


def _latest(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def node_bin() -> str:
    return (os.environ.get("HEVI_NODE")
            or _latest("/home/soffy/.nvm/versions/node/v*/bin/node")
            or shutil.which("node") or "node")


def chromium_bin() -> str | None:
    return (os.environ.get("MC_CHROMIUM")
            or _latest("/home/soffy/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))


def prepare_job(job_dir: Path, files: dict[str, str]) -> Path:
    """建 job 工程：配置 + node_modules 软链 + src 文件（相对路径 → 内容）。"""
    job_dir = Path(job_dir)
    (job_dir / "src").mkdir(parents=True, exist_ok=True)
    (job_dir / "vite.config.ts").write_text(VITE_CONFIG)
    (job_dir / "tsconfig.json").write_text(TSCONFIG)
    (job_dir / "package.json").write_text(PACKAGE)
    nm = job_dir / "node_modules"
    if not nm.exists():
        nm.symlink_to((MC_HOME / "node_modules").resolve())
    for rel, txt in files.items():
        p = job_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return job_dir


_OK = re.compile(r"RENDER OK: (\S+\.mp4) \((\d+) bytes, ([\d.]+)s, wall ([\d.]+)s")


def render_job(job_dir: Path, timeout: int = 300, port: int | None = None) -> dict:
    """跑 tools/render.mjs，返回 {file,size,duration,wall,log}；失败抛 RuntimeError。"""
    env = dict(os.environ)
    chrome = chromium_bin()
    if chrome:
        env["MC_CHROMIUM"] = chrome
    node = node_bin()
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    port = port or random.randint(9100, 9800)
    cmd = [node, str(MC_HOME / "tools" / "render.mjs"), str(job_dir), "--port", str(port), "--timeout", str(timeout)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 90, env=env)
    log = r.stdout + r.stderr
    (Path(job_dir) / "render-run.log").write_text(log)
    m = _OK.search(log)
    if r.returncode != 0 or not m:
        raise RuntimeError(f"Motion Canvas 渲染失败 rc={r.returncode}:\n{log[-2000:]}")
    return {"file": m.group(1), "size": int(m.group(2)), "duration": float(m.group(3)),
            "wall": round(time.time() - t0, 1), "log": log}
