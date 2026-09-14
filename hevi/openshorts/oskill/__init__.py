"""Deprecated compatibility module alias; implementation remains Layer4-owned."""

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hevi.openshorts.layer4_oskill import (
        create_publish_tickets,
        generate_ai_short,
        generate_clips,
        generate_youtube_package,
    )

__all__ = [
    "create_publish_tickets",
    "generate_ai_short",
    "generate_clips",
    "generate_youtube_package",
]

sys.modules[__name__] = importlib.import_module("hevi.openshorts.layer4_oskill")
