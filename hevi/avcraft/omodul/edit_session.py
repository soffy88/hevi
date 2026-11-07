"""统一编辑会话：剪辑与字幕共用 avcraft.timeline —— 逐句删/改字/改时、画面信号剪、断句修补，
一次导出 成片 + SRT/ASS + 硬字幕 + 软字幕。

CLI:
  # 1) 从字幕句建会话（视频=源；cues 在源时间轴）
  python -m hevi.avcraft.omodul.edit_session init VIDEO CUES.json SESSION.json [--repair --terms "A B,C D"] [--visual]
  # 2) 套用编辑操作（JSON 列表，见 oskill.timeline.apply_ops）
  python -m hevi.avcraft.omodul.edit_session ops SESSION.json OPS.json
  # 3) 导出
  python -m hevi.avcraft.omodul.edit_session export SESSION.json OUT_DIR [--burn] [--soft] [--mode bilingual|src|tr]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.avcraft.obase.media import (
    burn_subtitles,
    has_video,
    mux_soft_subs,
    probe_duration,
    render_keep_ranges,
    run_visual_detect,
)
from hevi.avcraft.oskill.subtitle import repair_breaks, to_ass, to_srt
from hevi.avcraft.oskill.timeline import (
    apply_ops,
    keep_ranges,
    load_timeline,
    merge_cut_signals,
    render_cues,
    save_timeline,
    timeline_from_cues,
)


def _load_cues(cues: list[dict] | str | Path) -> list[dict]:
    if isinstance(cues, (str, Path)):
        d = json.loads(Path(cues).read_text())
        return d["cues"] if isinstance(d, dict) else d
    return cues


_SENS = {"low": 0.2, "medium": 0.5, "high": 0.8}


def visual_detect_params(*, scene_threshold=None, still_sensitivity=None, still_min=None, black_min=None,
                         extra: dict | None = None) -> dict:
    """开放参数 → run_visual_detect 关键字参数（纯函数）。"""
    vp: dict = {}
    if scene_threshold is not None:
        vp["scene_th"] = float(max(0.0, min(100.0, scene_threshold)))
    if still_sensitivity is not None:
        s = _SENS.get(str(still_sensitivity).lower()) if isinstance(still_sensitivity, str) else still_sensitivity
        if s is None:
            raise ValueError(f"still_sensitivity: {still_sensitivity!r}")
        s = max(0.0, min(1.0, float(s)))
        vp["freeze_noise_db"] = round(-70.0 + 30.0 * s, 1)
    if still_min is not None:
        vp["freeze_min"] = float(still_min)
    if black_min is not None:
        vp["black_min"] = float(black_min)
    vp.update(extra or {})
    return vp


def init_session(
    video: str | Path,
    cues: list[dict] | str | Path,
    *,
    base_timeline: dict | str | Path | None = None,
    repair: bool = True,
    terms: list[str] | tuple = (),
    visual: bool = False,
    visual_policy: dict | None = None,
    scene_threshold: float | None = None,
    still_sensitivity: float | str | None = None,
    still_min: float | None = None,
    black_min: float | None = None,
    visual_params: dict | None = None,
) -> dict:
    """建会话时间线。base_timeline（如 pause_cut 产出）给定则沿用其 clips，并挂上 cues。

    开放参数（visual=True 时生效）：
      scene_threshold   scdet 阈值（0–100，越小越敏感，默认 10）
      still_sensitivity 静止检测灵敏度 0–1 或 low/medium/high（越高越容易判静止；映射 freezedetect 噪声门限 -70..-40 dB）
      still_min         静止最短秒数（同时用于检测与剪除，默认检测 1.5 / 剪除 2.0）
      black_min         黑场最短秒数；visual_params 直接透传 run_visual_detect（优先级最高）
    """
    video = Path(video).resolve()
    cs = _load_cues(cues)
    if repair:
        cs = repair_breaks(cs, terms=terms)
    dur = probe_duration(video)
    tl = timeline_from_cues(cs, dur, source=str(video))
    if base_timeline is not None:
        base = base_timeline if isinstance(base_timeline, dict) else load_timeline(base_timeline)
        tl["clips"], tl["params"] = base["clips"], dict(base.get("params", {}))
    for c, src in zip(tl["cues"], cs):
        if src.get("fix"):
            c["fix"] = src["fix"]
        if src.get("tr_stale"):
            c["tr_stale"] = True
    if visual and has_video(video):
        vp = visual_detect_params(scene_threshold=scene_threshold, still_sensitivity=still_sensitivity,
                                  still_min=still_min, black_min=black_min, extra=visual_params)
        sig = run_visual_detect(video, **vp)
        pol = dict(visual_policy or {})
        if still_min is not None:
            pol["freeze"] = {"min": still_min, **pol.get("freeze", {})}
        if black_min is not None:
            pol["black"] = {"min": black_min, **pol.get("black", {})}
        merge_cut_signals(tl, sig, pol or None)
        tl["params"]["visual_detect"] = vp
    return tl


def export_session(
    tl: dict | str | Path,
    out_dir: str | Path,
    *,
    stem: str | None = None,
    burn: bool = True,
    soft: bool = True,
    mode: str = "bilingual",
    fonts_dir: str | None = None,
) -> dict:
    tl = tl if isinstance(tl, dict) else load_timeline(tl)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(tl["source"])
    stem = stem or src.stem
    cut = render_keep_ranges(src, keep_ranges(tl), out / f"{stem}.edit{src.suffix}")
    cues = render_cues(tl)
    has_tr = any(c.get("tr") for c in cues)
    files = {"video": str(cut)}
    srt_src = out / f"{stem}.edit.src.srt"
    srt_src.write_text(to_srt(cues, "src"))
    files["srt_src"] = str(srt_src)
    if has_tr:
        srt_tr = out / f"{stem}.edit.tr.srt"
        srt_tr.write_text(to_srt(cues, "tr"))
        files["srt_tr"] = str(srt_tr)
    import subprocess

    from hevi.avcraft.obase.media import ffprobe_bin

    wh = subprocess.run([ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height", "-of", "csv=p=0", str(cut)],
                        capture_output=True, text=True).stdout.strip().split(",")
    w, h = (int(wh[0]), int(wh[1])) if len(wh) == 2 and wh[0] else (1920, 1080)
    ass_cues = cues if mode == "bilingual" else [
        {**c, "text": c.get("tr", "") if mode == "tr" else c["text"], "tr": ""} for c in cues]
    ass = out / f"{stem}.edit.ass"
    ass.write_text(to_ass(ass_cues, width=w, height=h, font="Noto Sans CJK SC"))
    files["ass"] = str(ass)
    if burn and w:
        files["burned"] = str(burn_subtitles(cut, ass, out / f"{stem}.edit.burned{src.suffix}",
                                             fonts_dir=fonts_dir))
    if soft:
        tracks = [{"path": srt_src, "lang": "eng", "title": "src", "default": True}]
        if has_tr:
            tracks.append({"path": out / f"{stem}.edit.tr.srt", "lang": "chi", "title": "tr", "default": False})
        files["soft_mp4"] = str(mux_soft_subs(cut, tracks, out / f"{stem}.edit.soft.mp4"))
        files["soft_mkv"] = str(mux_soft_subs(cut, [{"path": ass, "lang": "chi", "title": "bilingual-ass"},
                                                    *tracks], out / f"{stem}.edit.soft.mkv"))
    tl_path = save_timeline(tl, out / f"{stem}.edit.timeline.json")
    files["timeline"] = str(tl_path)
    return {
        "source_s": tl["duration"],
        "kept_s": round(sum(b - a for a, b in keep_ranges(tl)), 3),
        "output_s": round(probe_duration(cut), 3),
        "cues_out": len(cues),
        "cues_deleted": sum(1 for c in tl.get("cues", []) if c.get("deleted")),
        "ops": len(tl.get("ops", [])),
        "files": files,
    }


def _main() -> None:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("init")
    a.add_argument("video"), a.add_argument("cues"), a.add_argument("session")
    a.add_argument("--base-timeline")
    a.add_argument("--no-repair", action="store_true")
    a.add_argument("--terms", default="")
    a.add_argument("--visual", action="store_true")
    a.add_argument("--scene-th", type=float)
    a.add_argument("--still-sens", help="0-1 或 low/medium/high")
    a.add_argument("--still-min", type=float)
    a.add_argument("--black-min", type=float)
    b = sp.add_parser("ops")
    b.add_argument("session"), b.add_argument("ops")
    c = sp.add_parser("export")
    c.add_argument("session"), c.add_argument("out")
    c.add_argument("--no-burn", action="store_true")
    c.add_argument("--no-soft", action="store_true")
    c.add_argument("--mode", default="bilingual")
    x = ap.parse_args()
    if x.cmd == "init":
        tl = init_session(x.video, x.cues, base_timeline=x.base_timeline, repair=not x.no_repair,
                          terms=[t.strip() for t in x.terms.split(",") if t.strip()], visual=x.visual,
                          scene_threshold=x.scene_th, still_min=x.still_min, black_min=x.black_min,
                          still_sensitivity=(float(x.still_sens) if x.still_sens and x.still_sens[0].isdigit()
                                             else x.still_sens))
        save_timeline(tl, x.session)
        r = {"session": x.session, "clips": len(tl["clips"]), "cues": len(tl["cues"]),
             "fixed": sum(1 for c in tl["cues"] if c.get("fix")), "visual": tl["params"].get("visual_stats")}
    elif x.cmd == "ops":
        tl = apply_ops(load_timeline(x.session), json.loads(Path(x.ops).read_text()))
        save_timeline(tl, x.session)
        r = {"session": x.session, "ops": len(tl["ops"])}
    else:
        r = export_session(x.session, x.out, burn=not x.no_burn, soft=not x.no_soft, mode=x.mode)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _main()
