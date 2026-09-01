"""LongCat capability boundary owned by HEVI.

This package internalises the useful application-level parts of LongCat-2.0:
long-context packing, reasoning/tool-call normalisation, and long-horizon
agent execution.  LongCat weights and inference kernels remain optional
providers; HEVI never installs or vendors the upstream model.
"""

from hevi.longcat.omodul import (
    LongCatConfig,
    longcat_agent_workflow,
    longcat_capabilities,
)
from hevi.longcat.oprim import (
    LongCatContextBlock,
    LongCatRequest,
    LongCatTool,
    estimate_tokens,
    pack_context,
)
from hevi.longcat.oservi import (
    build_longcat_caller,
    longcat_provider_status,
)

__all__ = [
    "LongCatConfig",
    "LongCatContextBlock",
    "LongCatRequest",
    "LongCatTool",
    "build_longcat_caller",
    "estimate_tokens",
    "longcat_agent_workflow",
    "longcat_capabilities",
    "longcat_provider_status",
    "pack_context",
]
