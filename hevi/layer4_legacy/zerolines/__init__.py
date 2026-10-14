"""Layer4-owned zero-cost line engine (CPU only, no GPU, no paid API).

11 canonical Studio lines can render through this engine instead of their
original GPU/provider path (``engine="zero"`` on the order, or deployment-wide
``HEVI_LINE_ENGINE=zero``).  documentary_montage and localization_dub keep
their original implementation.
"""

from hevi.layer4_legacy.zerolines.oprim_impl.specs import (
    LEGACY_ONLY_LINES,
    LINE_SPECS,
    ZERO_LINES,
    ZeroLineRequest,
    resolve_engine,
)

__all__ = ["LEGACY_ONLY_LINES", "LINE_SPECS", "ZERO_LINES", "ZeroLineRequest", "resolve_engine", "zero_line_workflow"]


def zero_line_workflow(config, input_data, output_dir, *, on_step=None):
    """Lazy delegate (keeps numpy/PIL imports off the policy import path)."""
    from hevi.layer4_legacy.zerolines.omodul_impl.runtime import zero_line_workflow as _wf

    return _wf(config, input_data, output_dir, on_step=on_step)
