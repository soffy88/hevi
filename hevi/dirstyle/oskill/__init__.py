"""Deprecated compatibility shim; canonical HEVI implementation is Layer4-owned."""
from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt  # noqa: F401

__all__ = ["compile_prompt"]
