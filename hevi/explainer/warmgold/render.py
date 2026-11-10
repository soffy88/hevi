"""暖黑金图解渲染：HTML/CSS/SVG + Playwright 逐帧 + ffmpeg。

不引入 Remotion：用 hevi 自己的确定性逐帧路径（显式 seek + 软件 GL + 单并发）。
全片最多渲 2 遍；审片后只重渲改过的秒数。
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.explainer.warmgold import beats as beats_mod
from hevi.explainer.warmgold import parts as parts_mod
from hevi.explainer.warmgold import scriptcheck, style

PALETTE = style.STYLE_CARD["palette"]
COLOR = {
    "background": PALETTE["background"],
    "bg": PALETTE["background"],
    "panel": PALETTE["panel"],
    "ivory": PALETTE["ivory"],
    "ivory_dim": PALETTE["ivory_dim"],
    "gold": PALETTE["gold"],
    "gold_bright": PALETTE["gold_bright"],
    "danger": PALETTE["danger"],
    "past": PALETTE["past"],
    "none": "none",
}

CHROMIUM_ARGS = [
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--disable-dev-shm-usage",
    "--font-render-hinting=none",
    "--disable-lcd-text",
    "--disable-font-subpixel-positioning",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
]


@dataclass
class RenderReport:
    ok: bool
    out: str
    frames: int = 0
    passes: int = 0
    render_seconds: float = 0.0
    rerendered_seconds: float = 0.0
    contact_sheet: str = ""
    issues: list[dict[str, Any]] = field(default_factory=list)
    black_intervals: list[list[float]] = field(default_factory=list)
    freeze_intervals: list[list[float]] = field(default_factory=list)
    audio: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "out": self.out,
            "frames": self.frames,
            "passes": self.passes,
            "render_seconds": round(self.render_seconds, 2),
            "rerendered_seconds": round(self.rerendered_seconds, 2),
            "contact_sheet": self.contact_sheet,
            "issues": self.issues,
            "black_intervals": self.black_intervals,
            "freeze_intervals": self.freeze_intervals,
            "audio": self.audio,
        }


def _color_map(palette: dict[str, Any]) -> dict[str, str]:
    return {
        "background": palette["background"],
        "bg": palette["background"],
        "panel": palette["panel"],
        "ivory": palette["ivory"],
        "ivory_dim": palette["ivory_dim"],
        "gold": palette["gold"],
        "gold_bright": palette["gold_bright"],
        "danger": palette["danger"],
        "past": palette["past"],
        "none": "none",
    }


def _svg(items: list[dict[str, Any]], palette: dict[str, Any] | None = None) -> str:
    P = palette or PALETTE
    C = _color_map(P)
    out: list[str] = []
    for it in items:
        kind = it.get("k")
        color = C.get(str(it.get("f") or "gold"), str(it.get("f") or P["gold"]))
        opacity = float(it.get("o", 1.0))
        if kind == "c":
            out.append(
                f'<circle cx="{float(it["x"]) * 900:.1f}" cy="{float(it["y"]) * 760:.1f}" '
                f'r="{float(it["r"]) * 760:.1f}" fill="{color}" opacity="{opacity}"/>'
            )
        elif kind == "l":
            out.append(
                f'<line x1="{float(it["x1"]) * 900:.1f}" y1="{float(it["y1"]) * 760:.1f}" '
                f'x2="{float(it["x2"]) * 900:.1f}" y2="{float(it["y2"]) * 760:.1f}" '
                f'stroke="{color}" stroke-width="{float(it.get("w", 1)) * 2:.1f}" '
                f'opacity="{opacity}" stroke-linecap="round"/>'
            )
        elif kind == "r":
            stroke = it.get("s") or ""
            stroke_attr = (
                f' stroke="{C.get(str(stroke), P["gold"])}" stroke-width="2"'
                if stroke
                else ""
            )
            out.append(
                f'<rect x="{float(it["x"]) * 900:.1f}" y="{float(it["y"]) * 760:.1f}" '
                f'width="{float(it["w"]) * 900:.1f}" height="{float(it["h"]) * 760:.1f}" '
                f'rx="6" fill="{color}" opacity="{opacity}"{stroke_attr}/>'
            )
        elif kind == "p":
            pts = " ".join(f"{x * 900:.1f},{y * 760:.1f}" for x, y in it.get("pts") or [])
            out.append(
                f'<polyline points="{pts}" fill="none" stroke="{color}" '
                f'stroke-width="{float(it.get("w", 1.4)) * 1.6:.1f}" opacity="{opacity}" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )
        elif kind == "ring":
            out.append(
                f'<circle cx="{float(it["x"]) * 900:.1f}" cy="{float(it["y"]) * 760:.1f}" '
                f'r="{float(it["r"]) * 760:.1f}" fill="none" stroke="{color}" '
                f'stroke-width="2" stroke-dasharray="8 8" opacity="{opacity}"/>'
            )
        elif kind == "t":
            size = float(it.get("size", 0.026)) * 760
            anchor = {"middle": "middle", "start": "start", "end": "end"}.get(
                str(it.get("a")), "middle"
            )
            out.append(
                f'<text x="{float(it["x"]) * 900:.1f}" y="{float(it["y"]) * 760:.1f}" '
                f'font-family={style.FONT_SMALL!r} font-size="{size:.1f}" fill="{color}" '
                f'opacity="{opacity}" text-anchor="{anchor}" dominant-baseline="middle">'
                f"{_esc(str(it.get('s') or ''))}</text>"
            )
    return "".join(out)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fit_big(text: str) -> int:
    chars = len(text)
    if chars <= 10:
        return 96
    if chars <= 16:
        return 80
    if chars <= 24:
        return 66
    return 56


def _frame_plan(beat_data: dict[str, Any], fps: int) -> list[dict[str, Any]]:
    beats = list(beat_data.get("beats") or [])
    if not beats:
        return []
    beat_s = float(beat_data.get("beat_s") or 0.5)
    spans: list[dict[str, Any]] = []
    for beat in beats:
        if spans and spans[-1]["shot_id"] == beat["shot_id"]:
            spans[-1]["end"] = float(beat["t"]) + float(beat["duration"])
        else:
            spans.append(
                {
                    "shot_id": beat["shot_id"],
                    "start": float(beat["t"]),
                    "end": float(beat["t"]) + float(beat["duration"]),
                    "visual": beat.get("visual") or "",
                    "params": beat.get("params") or {},
                    "big": beat.get("big") or "",
                    "small": beat.get("small") or "",
                    "focus": beat.get("focus") or "",
                }
            )
    total = spans[-1]["end"] if spans else 0.0
    frames = max(1, math.ceil(total * fps))
    plan: list[dict[str, Any]] = []
    idx = 0
    for i in range(frames):
        t = i / fps
        while idx + 1 < len(spans) and t >= spans[idx + 1]["start"] - 1e-6:
            idx += 1
        span = spans[idx]
        dur = max(0.2, span["end"] - span["start"])
        local = (t - span["start"]) / dur
        fade_in = min(1.0, max(0.0, (t - span["start"]) / 0.12))
        alpha = max(0.72, fade_in)
        plan.append(
            {
                "i": i,
                "t": round(t, 4),
                "span": span,
                "local": min(1.0, max(0.0, local)),
                "alpha": round(alpha, 3),
                "beat_s": beat_s,
            }
        )
    return plan


def build_frame_html(
    plan: list[dict[str, Any]],
    palette: dict[str, Any] | None = None,
    *,
    label: str = "暖黑金图解 · WARM GOLD",
) -> str:
    P = palette or PALETTE
    scenes: list[list[Any]] = []
    for frame in plan:
        span = frame["span"]
        try:
            payload = parts_mod.draw(str(span["visual"]), span.get("params") or {}, frame["local"])
        except KeyError:
            payload = {"items": [], "readout": None, "sim_note": "", "part_id": ""}
        items = payload.get("items") or []
        if str(span.get("small") or "").strip():
            items = [
                it for it in items if not (it.get("k") == "t" and float(it.get("y") or 0) > 0.85)
            ]
        svg = _svg(items, P)
        readout = _esc(str(payload.get("readout") or ""))
        sim = _esc(str(payload.get("sim_note") or ""))
        big = _esc(str(span.get("big") or ""))
        small = _esc(str(span.get("small") or ""))
        scenes.append([svg, big, small, frame["alpha"], readout, sim])
    data = json.dumps(scenes, ensure_ascii=False)
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;overflow:hidden;background:{P["background"]}}}
body{{font-family:{style.FONT_SMALL};color:{P["ivory"]}}}
#root{{position:relative;width:1080px;height:1920px;background:
 radial-gradient(1100px 900px at 68% 12%, {P["panel"]} 0%, {P["background_soft"]} 46%, {P["background"]} 100%)}}
.grain{{position:absolute;inset:0;opacity:.05;background-image:
 repeating-linear-gradient(0deg,rgba(255,255,255,.22) 0 1px,transparent 1px 4px)}}
.hair{{position:absolute;left:80px;right:220px;height:1px;background:{P["gold"]};opacity:.22}}
#big{{position:absolute;top:176px;left:70px;width:940px;text-align:center;font-family:{style.FONT_BIG};
 font-weight:600;color:{P["ivory"]};line-height:1.14;letter-spacing:.01em;white-space:pre-line}}
#stage{{position:absolute;top:486px;left:60px;width:900px;height:760px}}
#stage svg{{width:900px;height:760px;display:block}}
#small{{position:absolute;top:1286px;left:84px;width:912px;text-align:center;font-size:44px;
 line-height:1.35;color:{P["ivory_dim"]};font-weight:400;white-space:pre-line}}
#readout{{position:absolute;top:486px;left:80px;font-family:{style.FONT_SMALL};font-size:40px;
 color:{P["gold_bright"]};letter-spacing:.04em}}
#sim{{position:absolute;top:1436px;left:84px;font-size:24px;color:{P["past"]};letter-spacing:.08em}}
#foot{{position:absolute;top:1500px;left:80px;right:220px;height:1px;background:{P["gold"]};opacity:.16}}
#mark{{position:absolute;top:1524px;left:84px;font-size:22px;color:{P["past"]};letter-spacing:.14em}}
</style></head><body><div id="root">
<div class="grain"></div><div class="hair"></div>
<div id="big"></div><div id="stage"></div><div id="readout"></div>
<div id="small"></div><div id="sim"></div><div id="foot"></div>
<div id="mark">{_esc(label)}</div>
</div><script id="scenes" type="application/json">{data}</script><script>
const S = JSON.parse(document.getElementById('scenes').textContent);
const big = document.getElementById('big'), small = document.getElementById('small');
const stage = document.getElementById('stage'), readout = document.getElementById('readout');
const sim = document.getElementById('sim');
window.__seek = function(i){{
  const f = S[i]; if(!f) return;
  stage.innerHTML = '<svg viewBox="0 0 900 760" xmlns="http://www.w3.org/2000/svg">'+f[0]+'</svg>';
  big.textContent = f[1]; small.textContent = f[2];
  big.style.fontSize = (f[1].length<=10?96:f[1].length<=16?80:f[1].length<=24?66:56)+'px';
  big.style.opacity = f[3]; small.style.opacity = f[3];
  stage.style.opacity = Math.min(1, f[3]+0.08);
  readout.textContent = f[4]; readout.style.opacity = f[3]*0.9;
  sim.textContent = f[5]; sim.style.opacity = f[3]*0.8;
}};
window.__ready = true;
window.__seek(0);
</script></body></html>"""


def _chromium_executable() -> str | None:
    for env_key in ("HEVI_CHROMIUM", "HEVI_LIVLIV_CHROME"):
        explicit = os.environ.get(env_key, "").strip()
        if explicit and Path(explicit).is_file():
            return explicit
    roots: list[Path] = []
    for env_key in ("PLAYWRIGHT_BROWSERS_PATH", "SCENE3D_PLAYWRIGHT_BROWSERS"):
        value = os.environ.get(env_key, "").strip()
        if value:
            roots.append(Path(value))
    roots += [Path.home() / ".cache" / "ms-playwright", Path("/pwbrowsers")]
    for root in roots:
        if not root.is_dir():
            continue
        candidates = sorted(
            root.glob(
                "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
            ),
            reverse=True,
        )
        candidates += sorted(root.glob("chromium-*/chrome-linux64/chrome"), reverse=True)
        candidates += sorted(root.glob("chromium-*/chrome-linux/chrome"), reverse=True)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def _launch_page(html: str) -> Any:
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    kwargs: dict[str, Any] = {"args": CHROMIUM_ARGS, "headless": True}
    executable = _chromium_executable()
    if executable:
        kwargs["executable_path"] = executable
    browser = pw.chromium.launch(**kwargs)
    page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
    page.set_content(html, wait_until="load")
    page.wait_for_function("window.__ready === true", timeout=30_000)
    return pw, browser, page


def _capture(page: Any, indices: list[int], frames_dir: Path, plan: list[dict[str, Any]]) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i in indices:
        page.evaluate("(i) => window.__seek(i)", i)
        page.screenshot(
            path=str(frames_dir / f"f_{i:06d}.png"), animations="disabled", caret="hide"
        )


def _encode(
    frames_dir: Path, out_mp4: Path, fps: int, audio: Path | None = None, start_number: int = 0
) -> None:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-framerate",
        str(fps),
        "-start_number",
        str(start_number),
        "-i",
        str(frames_dir / "f_%06d.png"),
    ]
    if audio and audio.is_file():
        cmd += ["-i", str(audio), "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {proc.stderr[:600]}")


def _piper_paths() -> tuple[Path, Path]:
    explicit = os.environ.get("HEVI_PIPER_BIN", "").strip()
    candidates = [
        explicit,
        shutil.which("piper") or "",
        "/data/soffy/projects/hevi-zero/.venv/bin/piper",
        "/usr/local/bin/piper",
    ]
    binary = next(
        (Path(p) for p in candidates if p and Path(p).is_file()), Path("/usr/local/bin/piper")
    )
    voices = Path(
        os.environ.get("HEVI_PIPER_VOICES_DIR", "") or "/data/soffy/projects/hevi-zero/voices"
    )
    if not voices.is_dir():
        voices = Path("/opt/piper/voices")
    return binary, voices


def _piper_synthesize(text: str, dest: Path, speed: float = 1.0) -> None:
    binary, voices = _piper_paths()
    model = voices / "zh_CN-huayan-medium.onnx"
    if not model.is_file():
        raise RuntimeError(f"piper voice not found: {model}")
    raw = dest.with_suffix(".raw.wav")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(binary),
            "-m",
            str(model),
            "-f",
            str(raw),
            "--length_scale",
            f"{1.0 / max(0.5, speed):.3f}",
            "--sentence_silence",
            "0.2",
        ],
        input=text.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr.decode('utf-8', 'ignore')[:300]}")
    norm = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(raw),
            "-af",
            "highpass=f=60,loudnorm=I=-16:TP=-1.5",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    raw.unlink(missing_ok=True)
    if norm.returncode != 0:
        raise RuntimeError(f"tts postprocess failed: {norm.stderr[:300]}")


def _tts_shots(script: dict[str, Any], work: Path) -> list[dict[str, Any]]:
    voice_dir = work / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for shot in script.get("shots") or []:
        text = str(shot.get("narration") or "").strip()
        if not text:
            rows.append({"shot": shot, "path": None, "duration": 0.0})
            continue
        dest = voice_dir / f"{shot.get('id') or 'shot'}.wav"
        if not dest.is_file():
            _piper_synthesize(text, dest, speed=float(shot.get("voice_speed") or 1.0))
        rows.append({"shot": shot, "path": dest, "duration": beats_mod.ffprobe_duration(dest)})
    return rows


def _mix_audio(
    tts_rows: list[dict[str, Any]],
    beat_data: dict[str, Any],
    total_s: float,
    work: Path,
    music_path: str | Path | None,
) -> Path | None:
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    input_index = 0
    for idx, row in enumerate(tts_rows):
        path = row.get("path")
        if not path or not Path(path).is_file():
            continue
        start_ms = round(_shot_start(row["shot"].get("id"), beat_data) * 1000)
        inputs += ["-i", str(path)]
        filters.append(f"[{input_index}:a]adelay={start_ms}|{start_ms}[v{idx}]")
        labels.append(f"[v{idx}]")
        input_index += 1
    if music_path and Path(music_path).is_file():
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        filters.append(
            f"[{input_index}:a]atrim=0:{total_s:.3f},volume=0.22,"
            f"afade=t=in:st=0:d=0.8,afade=t=out:st={max(0.0, total_s - 1.2):.3f}:d=1.2[music]"
        )
        labels.append("[music]")
        input_index += 1
    if not labels:
        return None
    if len(labels) == 1:
        filters.append(f"{labels[0]}anull[mix]")
    else:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
            f"alimiter=limit=0.95,atrim=0:{total_s:.3f}[mix]"
        )
    out = work / "mix.m4a"
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[mix]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"audio mix failed: {proc.stderr[:600]}")
    return out


def _shot_start(shot_id: Any, beat_data: dict[str, Any]) -> float:
    for beat in beat_data.get("beats") or []:
        if beat.get("shot_id") == shot_id:
            return float(beat["t"])
    return 0.0


def _contact_sheet(frames: list[Path], dest: Path, cols: int = 5) -> Path:
    from PIL import Image

    thumbs = []
    for path in frames:
        try:
            image = Image.open(path).convert("RGB")
            image.thumbnail((216, 384))
            thumbs.append(image)
        except OSError:
            continue
    if not thumbs:
        Image.new("RGB", (216, 384), (18, 14, 11)).save(dest)
        return dest
    w, h = 216, 384
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (18, 14, 11))
    for i, image in enumerate(thumbs):
        sheet.paste(image, ((i % cols) * w, (i // cols) * h))
    sheet.save(dest, quality=88)
    return dest


def _blackdetect(video: Path) -> tuple[list[list[float]], list[list[float]]]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video),
            "-vf",
            "blackdetect=d=0.15:pix_th=0.06,freezedetect=n=0.002:d=1.6",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    black: list[list[float]] = []
    freeze: list[list[float]] = []
    for line in proc.stderr.splitlines():
        if "black_start" in line:
            vals = dict(part.split(":", 1) for part in line.strip().split() if ":" in part)
            try:
                black.append(
                    [round(float(vals["black_start"]), 2), round(float(vals["black_end"]), 2)]
                )
            except KeyError, ValueError:
                continue
        if "freeze_start" in line:
            vals = dict(part.split(":", 1) for part in line.strip().split() if ":" in part)
            try:
                freeze.append(
                    [round(float(vals["freeze_start"]), 2), round(float(vals["freeze_end"]), 2)]
                )
            except KeyError, ValueError:
                continue
    return black, freeze


def _layout_issues(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    by_shot: dict[str, dict[str, Any]] = {}
    for frame in plan:
        span = frame["span"]
        sid = str(span["shot_id"])
        by_shot.setdefault(sid, {"start": frame["t"], "end": frame["t"] + 1 / 24, "span": span})
        by_shot[sid]["end"] = max(by_shot[sid]["end"], frame["t"])
    for sid, row in by_shot.items():
        span = row["span"]
        big = str(span.get("big") or "")
        if big:
            size = _fit_big(big)
            lines = math.ceil(max(1.0, style.text_width_px(big, size) / 940))
            bottom = 176 + lines * size * 1.14
            if bottom > 470:
                issues.append(
                    {
                        "code": "R01",
                        "shot": sid,
                        "message": f"大字压到画面区（{bottom:.0f}px）",
                        "fix": "删字或降字号",
                    }
                )
        if not big and not str(span.get("small") or ""):
            issues.append(
                {"code": "R02", "shot": sid, "message": "这一镜没有字", "fix": "给一句大字或小字"}
            )
    # >3 秒没有新东西
    last_event = None
    for frame in plan:
        sid = str(frame["span"]["shot_id"])
        if sid != last_event:
            last_event = sid
        elif frame["t"] - by_shot[sid]["start"] > 3.2 and not str(
            frame["span"].get("visual") or ""
        ):
            issues.append(
                {
                    "code": "R03",
                    "shot": sid,
                    "message": "同屏超过 3.2 秒没有新东西",
                    "fix": "加一个动作/换一个读数",
                }
            )
            break
    # 一屏多重点
    for sid, row in by_shot.items():
        focus = str(row["span"].get("focus") or "")
        if focus.count("；") + focus.count(";") > 0:
            issues.append(
                {"code": "R04", "shot": sid, "message": f"一屏多重点：{focus}", "fix": "只留一个"}
            )
    return issues


def _director_review(
    script: dict[str, Any],
    beat_data: dict[str, Any],
    checks: dict[str, Any],
    black: list[list[float]],
    freeze: list[list[float]],
) -> list[dict[str, Any]]:
    issues = list(checks.get("issues") or [])
    if black:
        issues.append(
            {
                "code": "D01",
                "severity": "fail",
                "message": f"黑帧 {black}",
                "fix": "检查首尾帧与转场",
                "at_s": black[0][0],
            }
        )
    issues.extend(
        {
            "code": "D02",
            "severity": "warn",
            "message": f"画面冻结 {a}–{b}s",
            "fix": "加一个读数变化",
            "at_s": a,
        }
        for a, b in freeze
        if b - a > 2.4
    )
    # 结尾动作必须具体
    ending = script.get("ending") or {}
    if len(str(ending.get("cta_text") or "")) < 6:
        issues.append(
            {
                "code": "D03",
                "severity": "fail",
                "message": "结尾互动句太短/太泛",
                "fix": "写成一句具体的话",
                "at_s": float(beat_data.get("total_s") or 0),
            }
        )
    # 排序：fail 优先，其次按时间。
    severity = {"fail": 0, "warn": 1}
    issues.sort(
        key=lambda x: (severity.get(str(x.get("severity") or "warn"), 2), float(x.get("at_s") or 0))
    )
    return issues[:3]


def preflight(script: dict[str, Any], beat_data: dict[str, Any], work: Path) -> dict[str, Any]:
    checks = scriptcheck.check_script(script, beat_data)
    plan = _frame_plan(beat_data, style.FPS)
    layout = _layout_issues(plan)
    return {"script": checks, "layout": layout, "pass": checks["pass"] and not layout}


def render(
    script: dict[str, Any],
    out_mp4: str | Path,
    *,
    workdir: str | Path,
    music_path: str | Path | None = None,
    voice: bool = True,
    fps: int = style.FPS,
    fixes: list[dict[str, Any]] | None = None,
) -> RenderReport:
    started = time.time()
    theme_palette = script.get("palette") if isinstance(script.get("palette"), dict) else None
    theme_label = "暖黑金图解 · WARM GOLD"
    if theme_palette:
        color = script.get("theme_color") or {}
        theme_label = f"知识讲解 · {color.get('name_zh', theme_palette.get('name', ''))} · {script.get('layout_id', '')}".strip(" ·")
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    out = Path(out_mp4)

    tts_rows: list[dict[str, Any]] = []
    if voice:
        tts_rows = _tts_shots(script, work)
        for row in tts_rows:
            if row["duration"] and Path(row["path"]).exists():
                shot = row["shot"]
                beat_s = 60.0 / float(script.get("bpm") or 120.0)
                need = math.ceil((row["duration"] + 0.25) / beat_s)
                shot["beats"] = max(int(shot.get("beats") or 0), need)
    total_needed = (
        sum(max(1, int(s.get("beats") or 1)) for s in script.get("shots") or [])
        * (60.0 / float(script.get("bpm") or 120.0))
        + 1.0
    )

    beat_data = beats_mod.build_beats(script, music_path=music_path, duration_floor=total_needed)
    pre = preflight(script, beat_data, work)
    if not pre["pass"]:
        # 只允许在修复清单存在时继续；否则把失败如实返回。
        hard = [i for i in pre["script"]["issues"] if i["severity"] == "fail"] + pre["layout"]
        if not fixes and hard:
            return RenderReport(
                ok=False,
                out=str(out),
                issues=hard,
                render_seconds=time.time() - started,
            )

    plan = _frame_plan(beat_data, fps)
    if not plan:
        return RenderReport(ok=False, out=str(out), issues=[{"message": "no frames"}])

    # 渲前联系表 + 手机尺寸测试图。
    event_indices = []
    seen = set()
    for frame in plan:
        sid = str(frame["span"]["shot_id"])
        if sid not in seen:
            seen.add(sid)
            event_indices.append(frame["i"])
    still_dir = work / "stills"
    pw, browser, page = _launch_page(build_frame_html(plan, theme_palette, label=theme_label))
    try:
        _capture(page, event_indices, still_dir, plan)
    finally:
        page.close()
        browser.close()
        pw.stop()
    sheet = _contact_sheet(
        [still_dir / f"f_{i:06d}.png" for i in event_indices], work / "preflight_sheet.jpg"
    )
    from PIL import Image

    try:
        phone = Image.open(still_dir / f"f_{event_indices[0]:06d}.png").convert("RGB")
        phone.thumbnail((270, 480))
        phone.save(work / "phone_test.jpg", quality=88)
    except OSError:
        pass

    # 正式逐帧。
    frames_dir = work / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    pw, browser, page = _launch_page(build_frame_html(plan, theme_palette, label=theme_label))
    try:
        _capture(page, list(range(len(plan))), frames_dir, plan)
    finally:
        page.close()
        browser.close()
        pw.stop()

    audio = _mix_audio(
        tts_rows, beat_data, float(beat_data.get("total_s") or 0.0), work, music_path
    )
    _encode(frames_dir, out, fps, audio=audio)
    passes = 1
    rerendered = 0.0

    black, freeze = _blackdetect(out)
    review = _director_review(
        script,
        beat_data,
        pre["script"] | {"issues": pre["script"]["issues"] + pre["layout"]},
        black,
        freeze,
    )

    # 只修最差 3 个；只重渲改过的秒数。
    if fixes and passes < 2:
        old = out.with_name(out.stem + "_pass1.mp4")
        shutil.move(out, old)
        pieces: list[Path] = []
        cursor = 0.0
        for fix in sorted(fixes, key=lambda f: float(f.get("start_s") or 0)):
            start = float(fix.get("start_s") or 0)
            end = float(fix.get("end_s") or start + 1)
            shot_id = str(fix.get("shot_id") or "")
            for shot in script.get("shots") or []:
                if str(shot.get("id")) == shot_id:
                    if fix.get("new_big") is not None:
                        shot["big"] = fix["new_big"]
                    if fix.get("new_small") is not None:
                        shot["small"] = fix["new_small"]
            for beat in beat_data.get("beats") or []:
                if str(beat.get("shot_id")) == shot_id:
                    if fix.get("new_big") is not None:
                        beat["big"] = fix["new_big"]
                    if fix.get("new_small") is not None:
                        beat["small"] = fix["new_small"]
            if start > cursor:
                piece = work / f"piece_{cursor:.2f}.mp4"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-ss",
                        f"{cursor}",
                        "-to",
                        f"{start}",
                        "-i",
                        str(old),
                        "-c",
                        "copy",
                        str(piece),
                    ],
                    check=False,
                )
                pieces.append(piece)
            new_plan = _frame_plan(beat_data, fps)
            part_frames = [f for f in new_plan if start <= f["t"] < end]
            if part_frames:
                pdir = work / f"patch_{start:.2f}"
                if pdir.exists():
                    shutil.rmtree(pdir)
                pw2, browser2, page2 = _launch_page(build_frame_html(new_plan, theme_palette, label=theme_label))
                try:
                    _capture(page2, [f["i"] for f in part_frames], pdir, new_plan)
                finally:
                    page2.close()
                    browser2.close()
                    pw2.stop()
                piece = work / f"patch_{start:.2f}.mp4"
                _encode(pdir, piece, fps, start_number=part_frames[0]["i"])
                pieces.append(piece)
                rerendered += end - start
            cursor = max(cursor, end)
        if cursor < float(beat_data.get("total_s") or 0):
            piece = work / "piece_tail.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    f"{cursor}",
                    "-i",
                    str(old),
                    "-c",
                    "copy",
                    str(piece),
                ],
                check=False,
            )
            pieces.append(piece)
        listfile = work / "concat.txt"
        listfile.write_text("".join(f"file '{p}'\n" for p in pieces), encoding="utf-8")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listfile),
                "-c",
                "copy",
                str(out),
            ],
            check=False,
        )
        if audio and audio.is_file():
            merged = work / "with_audio.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(out),
                    "-i",
                    str(audio),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    str(merged),
                ],
                check=False,
            )
            if merged.is_file():
                shutil.move(merged, out)
        black, freeze = _blackdetect(out)
        passes = 2

    elapsed = time.time() - started
    return RenderReport(
        ok=not black,
        out=str(out),
        frames=len(plan),
        passes=passes,
        render_seconds=elapsed,
        rerendered_seconds=rerendered,
        contact_sheet=str(sheet),
        issues=review,
        black_intervals=black,
        freeze_intervals=freeze,
        audio=str(audio or ""),
    )
