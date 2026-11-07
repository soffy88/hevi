"""横转竖跟随说话人：抽帧检测（YuNet/Haar/无）→ 目标选择 → 平滑轨迹 → ffmpeg sendcmd 驱动 crop → 9:16。

时间轴不变（只裁画面），所以同一时间线的 cues 直接按竖屏分辨率出 ASS 并可烧录 —— 与字幕时间线兼容。

CLI:
  python -m hevi.avcraft.omodul.reframe_vertical IN.mp4 OUT.mp4 [--cues CUES.json] [--size 1080x1920] [--no-face]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from hevi.avcraft.obase.media import burn_subtitles, ffmpeg_bin, probe_duration
from hevi.avcraft.obase.vision import analyze_frames
from hevi.avcraft.oskill.reframe import (
    crop_size,
    path_stats,
    per_frame_x,
    pick_targets,
    sendcmd_script,
    smooth_crop_path,
)
from hevi.avcraft.oskill.subtitle import to_ass


def reframe_vertical(
    video: str | Path,
    out: str | Path,
    *,
    cues: list[dict] | str | Path | None = None,
    size: tuple[int, int] = (1080, 1920),
    sample_fps: float = 4.0,
    faces: bool = True,
    smooth: dict | None = None,
    targets_opts: dict | None = None,
    burn: bool = True,
    crf: int = 23,
) -> dict:
    video, out = Path(video), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ana = analyze_frames(video, sample_fps=sample_fps, faces=faces)
    W, H, fps = ana["w"], ana["h"], ana["fps"]
    cw, ch = crop_size(W, H, size[0] / size[1])
    tg = pick_targets(ana["samples"], W, H, **(targets_opts or {}))
    path = smooth_crop_path(tg, W, cw, **(smooth or {}))
    dur = probe_duration(video)
    cmd_file = out.with_suffix(".crop.cmd")
    cmd_file.write_text(sendcmd_script(per_frame_x(path, fps, dur)))
    y0 = (H - ch) // 2
    x_init = path[0]["x0"] if path else (W - cw) // 2
    vf = (f"sendcmd=f='{cmd_file.as_posix()}',crop={cw}:{ch}:{x_init}:{y0},"
          f"scale={size[0]}:{size[1]}:flags=lanczos,setsar=1")
    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-vf", vf, "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(out)], check=True)
    files = {"video": str(out), "sendcmd": str(cmd_file)}
    if cues is not None:
        cs = json.loads(Path(cues).read_text()) if isinstance(cues, (str, Path)) else cues
        cs = cs["cues"] if isinstance(cs, dict) else cs
        cs = [c for c in cs if not c.get("deleted")]
        ass = out.with_suffix(".ass")
        ass.write_text(to_ass(cs, width=size[0], height=size[1], font="Noto Sans CJK SC"))
        files["ass"] = str(ass)
        if burn:
            files["burned"] = str(burn_subtitles(out, ass, out.with_name(out.stem + ".burned" + out.suffix)))
    track = out.with_suffix(".crop.json")
    track.write_text(json.dumps({"schema": "avcraft.crop_path/v1", "source": str(video), "src_size": [W, H],
                                 "crop": [cw, ch, y0], "out_size": list(size), "detector": ana["detector"],
                                 "path": path}, ensure_ascii=False))
    files["crop_path"] = str(track)
    return {"detector": ana["detector"], "src": [W, H], "crop": [cw, ch], "out_size": list(size),
            "output_s": round(probe_duration(out), 3), "stats": path_stats(path), "files": files}


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video"), ap.add_argument("out")
    ap.add_argument("--cues")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--no-face", action="store_true")
    ap.add_argument("--no-burn", action="store_true")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    r = reframe_vertical(a.video, a.out, cues=a.cues, size=(w, h), faces=not a.no_face, burn=not a.no_burn)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _main()
