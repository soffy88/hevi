"""Water ripple & refraction displacement transition (水面涟漪/折射位移过渡).

Inspired by awesome-ai-motion Case #13 (2102786378282987591 by Aurelien @Aurelien_Gz
and clearwater shallow-water physics).
Simulates dynamic shallow-water surface wave packets, Snell's law optical refraction
displacement, and specular caustic highlights. Headless CPU-only via vectorized NumPy and cv2.remap.
"""

from __future__ import annotations

import cv2
import numpy as np


def render_water_ripple(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """Render one frame of the water_ripple transition at progress p in [0, 1].

    Args:
        frame_a: Outgoing frame (H, W, 3) uint8 BGR.
        frame_b: Incoming frame (H, W, 3) uint8 BGR.
        p: Transition progress in [0, 1].
        params: Optional dict with customizable parameters:
            - center: (cx, cy) normalized center (default: (0.5, 0.5))
            - wave_speed: Expansion speed of wave front (default: 1.5)
            - refract_strength: Optical refraction displacement power (default: 0.04)
            - caustic_power: Brightness of specular caustic glints (default: 0.35)

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
    cx, cy = cfg.get("center", (0.5, 0.5))
    wave_speed = float(cfg.get("wave_speed", 1.5))
    refract_str = float(cfg.get("refract_strength", 0.04))
    caustic_power = float(cfg.get("caustic_power", 0.35))

    # Normalized coordinate grid
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u = (xx / w) - cx
    v = ((yy / h) - cy) * (h / w)  # Aspect-ratio corrected
    dist = np.sqrt(u * u + v * v)

    # AMFX-R2 H3: Compute screen bounds dynamically so wavefront progresses across full dur [0, 1]
    corners_u = [-cx, 1.0 - cx]
    corners_v = [-cy * (h / w), (1.0 - cy) * (h / w)]
    max_dist = float(max(np.sqrt(cu * cu + cv * cv) for cu in corners_u for cv in corners_v))

    transition_width = 0.20
    r_start = -transition_width
    r_end = max_dist + transition_width
    # Expanding wavefront radius traversing from before origin to beyond farthest corner
    r0 = r_start + (r_end - r_start) * p

    # Envelope fades in and out smoothly so p=0 and p=1 have zero disturbance
    # Envelope = sin(pi * p)
    envelope = np.sin(np.pi * p)

    # Wave packet calculation
    dr = dist - r0
    freq1 = 28.0
    freq2 = 42.0

    # Gaussian wave packet centered on the expanding wavefront
    packet1 = np.sin(freq1 * dr - 8.0 * p) * np.exp(- (dr / 0.16) ** 2)
    packet2 = 0.6 * np.sin(freq2 * dr - 14.0 * p) * np.exp(- ((dr + 0.04) / 0.20) ** 2)
    wave_height = (packet1 + packet2) * envelope

    # Compute spatial gradients of wave height for Snell refraction
    # dH/dx and dH/dy
    grad_y, grad_x = np.gradient(wave_height)

    # Displacement in pixels
    disp_x = grad_x * refract_str * w * 25.0
    disp_y = grad_y * refract_str * h * 25.0

    map_x = np.clip(xx + disp_x, 0.0, w - 1.0).astype(np.float32)
    map_y = np.clip(yy + disp_y, 0.0, h - 1.0).astype(np.float32)

    # Sample refracted frame A and frame B using cv2.remap (bilinear)
    refracted_a = cv2.remap(frame_a, map_x, map_y, cv2.INTER_LINEAR)
    refracted_b = cv2.remap(frame_b, map_x, map_y, cv2.INTER_LINEAR)

    # Blend between A and B across wavefront
    # Ahead of wavefront (dist > r0) is scene A; behind wavefront (dist < r0) is scene B
    alpha = np.clip((r0 - dist) / transition_width + 0.5, 0.0, 1.0)
    # Smoothstep
    s = alpha * alpha * (3.0 - 2.0 * alpha)
    s_alpha = s[:, :, np.newaxis]

    blended = (1.0 - s_alpha) * refracted_a.astype(np.float32) + s_alpha * refracted_b.astype(np.float32)

    # Specular Caustic Highlights (curvature of wave surface = Laplacian of height)
    laplacian = np.clip((grad_x ** 2 + grad_y ** 2) * 50.0, 0.0, 1.0)
    caustic_mask = laplacian * envelope * caustic_power
    caustic_color = np.array([255, 235, 185], dtype=np.float32)  # Aqua-white highlight in BGR
    blended += caustic_mask[:, :, np.newaxis] * caustic_color

    out = np.clip(blended, 0.0, 255.0).astype(np.uint8)
    return out
