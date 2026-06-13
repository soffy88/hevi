def get_xfade_filter(offset: float, duration: float = 1.0, transition_type: str = "fade") -> str:
    """Get FFmpeg xfade filter string for transitions between two streams.

    This is typically used when joining clips.
    """
    return f"xfade=transition={transition_type}:duration={duration}:offset={offset}"


def get_fade_in_out_filter(
    duration: float, start_fade_in: float = 0, end_fade_out: float | None = None
) -> str:
    """Get basic fade in/out filters for a single video."""
    filters = [f"fade=t=in:st={start_fade_in}:d=1"]
    if end_fade_out is not None:
        filters.append(f"fade=t=out:st={end_fade_out - 1}:d=1")
    return ",".join(filters)
