"""ShotSpec E2E 样片生成(GAP_PLAN §2 W1 step 4)。

产出 ``output/shotspec_e2e/``:
  - ``clips/`` 4 段 1080x1920/30fps/3s 的彩色 lavfi 素材(不同图案)
  - ``shotspec.mp4``   3 镜带 spec(镜4 无 spec)的成片
  - ``baseline.mp4``   同素材、无 spec 的基线成片
  - ``shotspec_repatch.mp4`` 经 API PATCH 改镜1 spec 后重渲的成片
  - ``record.json``    命令 / filter_complex / ffprobe / sha256 / spec JSON

通过真实 API(TestClient + 内存仓库)对镜1 做 PATCH,读回后重渲,证明 spec 改动
生效——不 mock 渲染路径。所有 ffmpeg 调用真实执行,记录真实 filter_complex。

跑法: PYTHONPATH=$PWD .venv/bin/python scripts/shot_spec_demo.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

# API 部分(TestClient)会加载 hevi.core.config,要求 JWT_SECRET;本地演示给个默认值。
os.environ.setdefault("JWT_SECRET", "test-secret-local")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "output" / "shotspec_e2e"
CLIPS = OUT / "clips"
W, H, FPS, DUR = 1080, 1920, 30, 3.0
XFADE_D = 0.5

# 4 镜素材:不同彩色 lavfi 图案(1080x1920 竖屏)。
CLIP_SOURCES = [
    "gradients=s=1080x1920:c0=0x1a237e:c1=0xff6f00:d=3:rate=30",
    "smptehdbars=s=1080x1920:d=3:rate=30",
    "rgbtestsrc=s=1080x1920:d=3:rate=30",
    "testsrc2=s=1080x1920:d=3:rate=30",
]

# 3 份不同 spec(镜4 无 spec → None)。
SPEC_DICTS: list[dict[str, Any] | None] = [
    {"effect": "warm", "sfx": [{"id": "whoosh_air_up", "offset": 1.0}], "duration": DUR},
    {
        "transition_in": "dissolve",
        "effect": "mono",
        "sfx": [
            {"id": "impact_hard", "offset": 0.5},
            {"id": "ding_bell", "offset": 2.0},
        ],
        "duration": DUR,
    },
    {
        "transition_in": "whip",
        "effect": "cool",
        "sfx": [{"id": "pop_dry", "offset": 1.5}],
        "duration": DUR,
    },
    None,
]


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def _ffprobe(path: Path) -> dict[str, Any]:
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_frames",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(out)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_clips() -> list[Path]:
    CLIPS.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, src in enumerate(CLIP_SOURCES):
        p = CLIPS / f"shot{i}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                src,
                "-t",
                str(DUR),
                "-r",
                str(FPS),
                "-pix_fmt",
                "yuv420p",
                str(p),
            ]
        )
        paths.append(p)
    return paths


def _render(clips: list[Path], out: Path, specs: list[Any] | None, capture: dict) -> None:
    """跑一次真实装配,并把真实 ffmpeg args(filter_complex)记进 capture。"""
    import hevi.assembly.assembler as asm
    from hevi.assembly.assembler import ShotSegment

    original = asm.ffmpeg_run

    async def _spy(*, args, expected_output, **kw):
        capture.setdefault("ffmpeg_calls", []).append(
            {"args": [str(a) for a in args], "expected_output": str(expected_output)}
        )
        return await original(args=args, expected_output=expected_output, **kw)

    asm.ffmpeg_run = _spy
    try:
        asyncio.run(
            asm.assemble_longvideo(
                shots=[ShotSegment(video_path=c) for c in clips],
                output_path=out,
                shot_specs=specs,
                transition="fade",
                transition_duration=XFADE_D,
                width=W,
                height=H,
                fps=FPS,
                color_normalize=False,
            )
        )
    finally:
        asm.ffmpeg_run = original


def _api_patch_spec(shot_index: int, patch: dict[str, Any]) -> dict[str, Any]:
    """用真实 API(TestClient + 内存仓库)对某镜做 PATCH,返回读回的 spec。"""
    from fastapi.testclient import TestClient

    from hevi.api.main import app
    from hevi.api.routers.tasks import get_repository
    from hevi.auth.dependencies import get_current_user

    task_id = uuid4()
    user = {"id": "shotspec-demo"}
    shots = [
        {"id": uuid4(), "task_id": str(task_id), "shot_index": i, "selection_json": {}}
        for i in range(len(SPEC_DICTS))
    ]

    class _Repo:
        async def get_task(self, tid):
            return {"id": str(task_id), "user_id": user["id"]}

        async def get_shots(self, tid):
            return shots

        async def save_shot(self, row):
            for i, s in enumerate(shots):
                if s["id"] == row["id"]:
                    shots[i] = row

    repo = _Repo()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        client = TestClient(app)
        # 先把初始 3 份 spec 写进去(PUT 批量),再 PATCH 单镜。
        put = client.put(
            f"/api/tasks/{task_id}/shots/spec",
            json={
                "specs": [
                    {"shot_index": i, "spec": s} for i, s in enumerate(SPEC_DICTS) if s is not None
                ]
            },
        )
        assert put.status_code == 200, put.text
        r = client.patch(f"/api/tasks/{task_id}/shots/{shot_index}/spec", json=patch)
        assert r.status_code == 200, r.text
        back = client.get(f"/api/tasks/{task_id}/shots/{shot_index}/spec").json()
        client.close()
        return back["spec"]
    finally:
        app.dependency_overrides.clear()


def main() -> int:
    from hevi.production.shot_spec import ShotSpec

    OUT.mkdir(parents=True, exist_ok=True)
    clips = _make_clips()
    specs = [ShotSpec.model_validate(s) if s else None for s in SPEC_DICTS]

    record: dict[str, Any] = {
        "width": W,
        "height": H,
        "fps": FPS,
        "shot_duration": DUR,
        "transition_duration": XFADE_D,
        "clip_sources": CLIP_SOURCES,
        "specs": [s.model_dump() if s else None for s in specs],
    }

    # ① 带 spec 渲染
    cap_spec: dict = {}
    spec_out = OUT / "shotspec.mp4"
    _render(clips, spec_out, specs, cap_spec)
    record["shotspec"] = {
        "path": str(spec_out.relative_to(REPO)),
        "ffprobe": _ffprobe(spec_out),
        "sha256": _sha256(spec_out),
        "ffmpeg_calls": cap_spec["ffmpeg_calls"],
    }

    # ② 无 spec 基线(同素材)
    cap_base: dict = {}
    base_out = OUT / "baseline.mp4"
    _render(clips, base_out, None, cap_base)
    record["baseline"] = {
        "path": str(base_out.relative_to(REPO)),
        "ffprobe": _ffprobe(base_out),
        "sha256": _sha256(base_out),
        "ffmpeg_calls": cap_base["ffmpeg_calls"],
    }

    # ③ 经 API PATCH 改镜1(index0)spec: warm → vignette,再重渲
    patched = _api_patch_spec(0, {"effect": "vignette"})
    record["repatch"] = {"patch": {"shot_index": 0, "effect": "vignette"}, "spec_after": patched}
    specs_repatch = list(specs)
    specs_repatch[0] = ShotSpec.model_validate(patched)
    cap_re: dict = {}
    re_out = OUT / "shotspec_repatch.mp4"
    _render(clips, re_out, specs_repatch, cap_re)
    record["shotspec_repatch"] = {
        "path": str(re_out.relative_to(REPO)),
        "ffprobe": _ffprobe(re_out),
        "sha256": _sha256(re_out),
        "ffmpeg_calls": cap_re["ffmpeg_calls"],
    }

    # 清理临时裁剪脚本目录? 不——output 被 gitignore,保留素材供验收复用。
    (OUT / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote", OUT / "record.json")
    print("spec dur", record["shotspec"]["ffprobe"]["format"]["duration"])
    print("base dur", record["baseline"]["ffprobe"]["format"]["duration"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
