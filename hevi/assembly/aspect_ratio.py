from enum import StrEnum


class AspectRatio(StrEnum):
    RATIO_9_16 = "9:16"  # 竖屏 (hevi 主打)
    RATIO_16_9 = "16:9"  # 横屏
    RATIO_1_1 = "1:1"  # 方形


def get_aspect_ratio_filter(
    ratio: AspectRatio | str, target_res: tuple[int, int] = (1080, 1920)
) -> str:
    """Get FFmpeg filter string for aspect ratio conversion.

    Default target is 1080x1920 (9:16).
    Uses 'crop' or 'pad' logic. For simplicity, we implement 'crop' to fill.
    """
    r = str(ratio)
    if r == AspectRatio.RATIO_9_16:
        # Assuming input is 16:9, we crop the sides
        return "crop=ih*9/16:ih"
    elif r == AspectRatio.RATIO_16_9:
        # Assuming input is 16:9, no crop
        return "scale=1920:1080"
    elif r == AspectRatio.RATIO_1_1:
        # Crop to center square
        return "crop=ih:ih"
    else:
        raise ValueError(f"Unsupported aspect ratio: {r}")
