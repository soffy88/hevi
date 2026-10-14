"""Ken Burns camera motion filter generator for vertical comic video.

3O Pillar: oprim.comicnarr_ken_burns
"""

from __future__ import annotations

CAMERA_MOVES = ("push", "pan_r", "pull", "pan_l")


def build_ken_burns_filter(
    *,
    move: str,
    duration: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 25,
) -> str:
    """Generate ffmpeg -vf filter string for Ken Burns camera motion.

    Pre-scales the source image by 1.25x to guarantee crisp framing without blurred edges.
    """
    d = max(0.5, float(duration))
    w = int(width)
    h = int(height)
    m = (move or "push").lower()

    # Pre-scale dimensions (1.25x)
    sw = int(w * 1.25) // 2 * 2
    sh = int(h * 1.25) // 2 * 2

    if m == "push":
        # Slow zoom in: scale factor from 1.0 to 1.15
        k = f"(1.0+0.15*t/{d:.3f})"
        return (
            f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"scale=w='trunc({w}*{k}/2)*2':h='trunc({h}*{k}/2)*2':eval=frame,"
            f"crop={w}:{h}:x='(iw-{w})/2':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )
    elif m == "pull":
        # Slow zoom out: scale factor from 1.15 down to 1.0
        k = f"(1.15-0.15*t/{d:.3f})"
        return (
            f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"scale=w='trunc({w}*{k}/2)*2':h='trunc({h}*{k}/2)*2':eval=frame,"
            f"crop={w}:{h}:x='(iw-{w})/2':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )
    elif m == "pan_l":
        # Smooth pan from right to left
        return (
            f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"crop={w}:{h}:x='(iw-{w})*(1.0-t/{d:.3f})':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )
    else:  # pan_r
        # Smooth pan from left to right
        return (
            f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"crop={w}:{h}:x='(iw-{w})*(t/{d:.3f})':y='(ih-{h})/2',setsar=1,format=yuv420p"
        )


__all__ = [
    "CAMERA_MOVES",
    "build_ken_burns_filter",
]
