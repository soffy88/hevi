"""Deprecated compatibility module alias; implementation remains Layer4-owned."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("hevi.layer4_legacy.montage.omodul_impl.agentic")
