"""横转竖跟随说话人：目标点选择 + 平滑裁切轨迹（思路：ClipsAI resize 的“说话人框→裁切窗”，纯函数）。

目标优先级：人脸（与上一目标最近的连续轨迹；多脸取最大/最靠近）→ 失脸后保持 hold_s 秒 →
运动显著区（运动能量够大时取运动质心）→ 画面中心。
平滑：死区（小抖不动）+ 指数平滑 + 最大速度限制，再输出逐帧 x（ffmpeg sendcmd 可直接用）。
"""

from __future__ import annotations

from itertools import pairwise


def crop_size(src_w: int, src_h: int, aspect: float = 9 / 16) -> tuple[int, int]:
    """源内最大的 aspect(宽/高) 裁切窗，偶数像素。"""
    cw, ch = src_h * aspect, src_h
    if cw > src_w:
        cw, ch = src_w, src_w / aspect
    return int(cw) // 2 * 2, int(ch) // 2 * 2


def pick_targets(
    samples: list[dict],
    src_w: int,
    src_h: int,
    *,
    hold_s: float = 1.0,
    motion_min: float = 0.01,
    min_face_frac: float = 0.012,
    speaker_weight: float = 4.0,
) -> list[dict]:
    """每个采样点的目标中心 x（源像素）及来源 face|hold|motion|center。

    多张脸时打分：面积 + 与上一目标的连续性 + 检测分 + speaker_weight×嘴部活动（obase 帧差近似）。
    """
    out, last_face_t, last_x = [], None, src_w / 2
    for s in samples:
        faces = [f for f in s.get("faces", []) if f[2] >= min_face_frac * src_w]
        src, x = None, None
        if faces:
            # 连续性优先：离上一目标近的加分；面积大的加分（主说话人通常更大、更居中）
            def key(f, last_x=last_x):
                cx = f[0] + f[2] / 2
                act = f[5] if len(f) > 5 else 0.0  # 嘴部活动越大越像正在说话的人
                return (f[2] * f[3] / (src_w * src_h) - abs(cx - last_x) / src_w * 0.5 + 0.05 * f[4]
                        + speaker_weight * act)
            f = max(faces, key=key)
            x, src, last_face_t = f[0] + f[2] / 2, "face", s["t"]
        elif last_face_t is not None and s["t"] - last_face_t <= hold_s:
            x, src = last_x, "hold"
        elif s.get("motion", 0.0) >= motion_min:
            x, src = s.get("mx", 0.5) * src_w, "motion"
        else:
            x, src = src_w / 2, "center"
        out.append({"t": s["t"], "x": x, "src": src})
        last_x = x
    return out


def smooth_crop_path(
    targets: list[dict],
    src_w: int,
    crop_w: int,
    *,
    alpha: float = 0.25,
    dead_zone: float = 0.06,
    max_speed: float = 0.35,
) -> list[dict]:
    """目标中心 → 平滑后的裁切左边界 x0（已夹在 [0, src_w-crop_w]）。

    dead_zone: 目标偏离当前中心 < dead_zone*crop_w 时不动；max_speed: 每秒最多移动 max_speed*src_w。
    """
    if not targets:
        return []
    half, lim = crop_w / 2, max(0, src_w - crop_w)
    cx = min(max(targets[0]["x"], half), src_w - half)
    out, prev_t = [], targets[0]["t"]
    for tg in targets:
        dt = max(1e-3, tg["t"] - prev_t)
        prev_t = tg["t"]
        goal = min(max(tg["x"], half), src_w - half)
        if abs(goal - cx) > dead_zone * crop_w:
            step = alpha * (goal - cx)
            cap = max_speed * src_w * dt
            cx += max(-cap, min(cap, step))
        out.append({"t": tg["t"], "x0": round(min(max(cx - half, 0), lim)), "src": tg["src"]})
    return out


def per_frame_x(path: list[dict], fps: float, duration: float) -> list[tuple[float, int]]:
    """采样点间线性插值成逐帧 (t, x0)，用于 ffmpeg sendcmd 驱动 crop。"""
    if not path:
        return []
    out, k = [], 0
    n = int(duration * fps) + 1
    for i in range(n):
        t = i / fps
        while k + 1 < len(path) and path[k + 1]["t"] <= t:
            k += 1
        a = path[k]
        b = path[k + 1] if k + 1 < len(path) else a
        if b["t"] > a["t"] and t > a["t"]:
            r = min(1.0, (t - a["t"]) / (b["t"] - a["t"]))
            x = a["x0"] + r * (b["x0"] - a["x0"])
        else:
            x = a["x0"]
        out.append((round(t, 4), round(x) // 2 * 2))
    return out


def sendcmd_script(frames: list[tuple[float, int]]) -> str:
    """只在 x 变化时下发命令，减小脚本体积。"""
    lines, last = [], None
    for t, x in frames:
        if x != last:
            lines.append(f"{t:.4f} crop x {x};")
            last = x
    return "\n".join(lines) + "\n"


def path_stats(path: list[dict]) -> dict:
    srcs: dict[str, int] = {}
    for p in path:
        srcs[p["src"]] = srcs.get(p["src"], 0) + 1
    jumps = [abs(b["x0"] - a["x0"]) for a, b in pairwise(path)]
    return {"samples": len(path), "sources": srcs, "max_step_px": max(jumps) if jumps else 0,
            "mean_step_px": round(sum(jumps) / len(jumps), 2) if jumps else 0}
