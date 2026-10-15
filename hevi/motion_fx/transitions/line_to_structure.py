"""Line-to-structure transition (线条描绘→结构体形变接下一镜).

Inspired by awesome-ai-motion Case #9 (2109174851412119558 by Nick @heyiamnick).
Transforms outgoing scene into dynamic technical blueprint sketch lines,
morphs line contours into an isometric/geometric structural wireframe,
and fills in the incoming scene's textures and surfaces.
"""

from __future__ import annotations

import cv2
import numpy as np


def render_line_to_structure(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """Render one frame of the line_to_structure transition at progress p in [0, 1].

    Args:
        frame_a: Outgoing frame (H, W, 3) uint8 BGR.
        frame_b: Incoming frame (H, W, 3) uint8 BGR.
        p: Transition progress in [0, 1].
        params: Optional dict with customizable parameters:
            - line_color: BGR tuple for line drawing (default: [245, 215, 60] cyan-white)
            - bg_color: BGR tuple for blueprint background (default: [55, 25, 12] deep navy)
            - grid_spacing: Pixel spacing for architectural grid (default: 48)

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
    line_col = np.array(cfg.get("line_color", [245, 215, 60]), dtype=np.float32)
    bg_col = np.array(cfg.get("bg_color", [55, 25, 12]), dtype=np.float32)
    grid_spacing = int(cfg.get("grid_spacing", 48))

    # Convert to float
    fa = frame_a.astype(np.float32)
    fb = frame_b.astype(np.float32)

    # 1. Edge maps
    gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)

    edges_a = cv2.Canny(gray_a, 40, 120).astype(np.float32) / 255.0
    edges_b = cv2.Canny(gray_b, 40, 120).astype(np.float32) / 255.0

    k = np.ones((2, 2), np.uint8)
    edges_a = cv2.dilate(edges_a, k)[:, :, np.newaxis]
    edges_b = cv2.dilate(edges_b, k)[:, :, np.newaxis]

    # 2. Architectural Blueprint Grid
    # Create coordinate grid
    yy, xx = np.mgrid[0:h, 0:w]
    grid_mask = ((xx % grid_spacing == 0) | (yy % grid_spacing == 0)).astype(np.float32)
    # Add diagonal isometric guide lines
    iso_mask = ((xx + yy) % (grid_spacing * 2) == 0).astype(np.float32)
    grid_total = np.clip(grid_mask * 0.25 + iso_mask * 0.15, 0.0, 1.0)[:, :, np.newaxis]

    blueprint_base = bg_col + grid_total * np.array([120, 70, 30], dtype=np.float32)

    # 3. Dynamic sweep and phase weighting
    # Phase 1: Deconstruction of A into sketch lines (p: 0 -> 0.45)
    # Phase 2: Morphing structural wireframe (p: 0.25 -> 0.75)
    # Phase 3: Solidification of B from structural lines (p: 0.55 -> 1.0)

    # Weight of photo A
    w_photo_a = max(0.0, 1.0 - p / 0.4)
    # Weight of photo B
    w_photo_b = max(0.0, (p - 0.6) / 0.4)

    # Line drawing of A: outlines over fading photo A
    a_sketch = fa * (1.0 - edges_a * 0.8) + line_col * edges_a

    # Morphing wireframe edges between A and B
    alpha_morph = np.clip((p - 0.2) / 0.6, 0.0, 1.0)
    # Smoothstep interpolation for edges
    s_morph = alpha_morph * alpha_morph * (3.0 - 2.0 * alpha_morph)
    morphed_edges = (1.0 - s_morph) * edges_a + s_morph * edges_b

    # Scanning sweep wavefront across the width
    sweep_x = p * (w + 100) - 50
    dist_to_sweep = (xx - sweep_x).astype(np.float32)
    sweep_glow = np.exp(- (dist_to_sweep ** 2) / (2.0 * (35.0 ** 2)))[:, :, np.newaxis]
    sweep_highlight = sweep_glow * np.array([255, 255, 255], dtype=np.float32)

    # Blueprint stage: navy background + grid + glowing structural lines
    structure_stage = blueprint_base + morphed_edges * (line_col * 1.2) + sweep_highlight * 0.8

    # Blend stages according to timeline
    if p < 0.35:
        t = p / 0.35
        # Transition from A to sketch to blueprint structure
        out = (1.0 - t) * a_sketch + t * structure_stage
    elif p < 0.65:
        # Pure structure morphing phase with scanning beam and wireframes
        out = structure_stage
    else:
        t = (p - 0.65) / 0.35
        # Solidify structure into B
        # B expands from wireframe edges to full color
        b_sketch = fb * (1.0 - edges_b * 0.4) + line_col * edges_b * (1.0 - t)
        out = (1.0 - t) * structure_stage + t * b_sketch

    # Final blend with target photo B
    if w_photo_b > 0.0:
        out = (1.0 - w_photo_b) * out + w_photo_b * fb

    out = np.clip(out, 0.0, 255.0).astype(np.uint8)
    return out
