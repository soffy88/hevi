"""Glass refraction sweep transition (透明/折射材质扫过).

Inspired by awesome-ai-motion Case #12 (2109257723246501895 by Ann Nguyen @ann_nnng).
Simulates a thick transparent optical glass prism slab sweeping across the screen,
featuring Snell's law refraction, chromatic aberration (RGB prism dispersion),
Fresnel bevel reflections, and specular glass sheen.
"""

from __future__ import annotations

import cv2
import numpy as np


def render_glass_refract(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """Render one frame of the glass_refract transition at progress p in [0, 1].

    Args:
        frame_a: Outgoing frame (H, W, 3) uint8 BGR.
        frame_b: Incoming frame (H, W, 3) uint8 BGR.
        p: Transition progress in [0, 1].
        params: Optional dict with customizable parameters:
            - angle_deg: Slant angle of glass slab in degrees (default: 18.0)
            - slab_width: Relative thickness of glass pane (default: 0.35 of width)
            - refract_strength: Displacement magnitude of refraction (default: 0.06)
            - dispersion: Chromatic aberration strength (default: 0.012, max safe limit: 0.015 to avoid prohibited RGB split)
            - glint_power: Specular bevel highlight intensity (default: 0.6)

    Returns:
        Rendered frame (H, W, 3) uint8 BGR.
    """
    if p <= 0.0:
        return frame_a.copy()
    if p >= 1.0:
        return frame_b.copy()

    h, w = frame_a.shape[:2]
    if frame_b.shape[:2] != (h, w):
        frame_b = cv2.resize(frame_b, (w, h), interpolation=cv2.INTER_LINEAR)

    cfg = params or {}
    angle_deg = float(cfg.get("angle_deg", 18.0))
    slab_w_rel = float(cfg.get("slab_width", 0.35))
    refract_str = float(cfg.get("refract_strength", 0.06))
    raw_dispersion = float(cfg.get("dispersion", 0.012))
    # AMFX-R2 H4: Cap chromatic dispersion at 0.015 to prevent prohibited RGB split
    dispersion = min(0.015, max(0.0, raw_dispersion))
    glint_power = float(cfg.get("glint_power", 0.6))

    theta = np.radians(angle_deg)
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)

    # Glass pane width in pixels
    w_glass = w * slab_w_rel
    half_w = w_glass / 2.0

    # Coordinate grids
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # 1D projection along normal to glass slab
    proj = xx * cos_t + yy * sin_t
    max_proj = w * cos_t + h * sin_t

    # Glass center sweeps smoothly from -half_w to max_proj + half_w
    glass_center = (max_proj + 2.0 * w_glass) * p - w_glass

    # Distance to glass centerline
    dist = proj - glass_center
    u = dist / half_w  # u in [-1, 1] inside glass slab

    # Mask for inside glass slab
    in_glass = np.abs(u) <= 1.0

    # Base transition weight: ahead of glass (u > 1) = A (0.0), behind glass (u < -1) = B (1.0)
    # Inside glass: smooth blend transitioning across the glass body
    alpha = np.clip(0.5 - 0.5 * u, 0.0, 1.0)
    # Smoothstep
    s_alpha = alpha * alpha * (3.0 - 2.0 * alpha)

    # Refraction displacement profile: beveled prism lens profile
    # Slope of curved glass surface displaces coordinates perpendicular to slab
    # disp ~ -u * (1 - u^2)
    slope = -u * np.maximum(0.0, 1.0 - u * u) * 2.5
    disp_base = np.where(in_glass, slope * refract_str * w, 0.0).astype(np.float32)

    disp_x = disp_base * cos_t
    disp_y = disp_base * sin_t

    # Chromatic aberration: Separate channels (B, G, R in OpenCV)
    # Blue bends more, Red bends less
    disp_r_x = disp_x * (1.0 - dispersion)
    disp_r_y = disp_y * (1.0 - dispersion)
    disp_g_x = disp_x
    disp_g_y = disp_y
    disp_b_x = disp_x * (1.0 + dispersion)
    disp_b_y = disp_y * (1.0 + dispersion)

    # Sample channels for frame A and frame B
    out_bgr = np.zeros((h, w, 3), dtype=np.float32)

    # Channel indices: 0=B, 1=G, 2=R
    for ch, (dx, dy) in enumerate([
        (disp_b_x, disp_b_y),
        (disp_g_x, disp_g_y),
        (disp_r_x, disp_r_y),
    ]):
        map_x = np.clip(xx + dx, 0.0, w - 1.0).astype(np.float32)
        map_y = np.clip(yy + dy, 0.0, h - 1.0).astype(np.float32)

        samp_a = cv2.remap(frame_a[:, :, ch], map_x, map_y, cv2.INTER_LINEAR)
        samp_b = cv2.remap(frame_b[:, :, ch], map_x, map_y, cv2.INTER_LINEAR)

        ch_blend = (1.0 - s_alpha) * samp_a.astype(np.float32) + s_alpha * samp_b.astype(np.float32)
        out_bgr[:, :, ch] = ch_blend

    # Specular Glint along bevels (|u| near 0.88 - 0.98)
    glint_mask = np.exp(- ((np.abs(u) - 0.92) ** 2) / 0.015) * in_glass
    # Add subtle sheen across the glass face
    sheen_mask = np.maximum(0.0, 1.0 - u * u) * 0.12 * in_glass

    total_highlight = (glint_mask * glint_power + sheen_mask)[:, :, np.newaxis]
    specular_color = np.array([255, 250, 245], dtype=np.float32)  # Pristine crystal highlight

    out_bgr += total_highlight * specular_color

    out = np.clip(out_bgr, 0.0, 255.0).astype(np.uint8)
    return out
