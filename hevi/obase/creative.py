"""Deprecated lazy compatibility facade for HEVI Layer4 creative contracts."""

from importlib import import_module

_TARGET = import_module("hevi.layer4_legacy.obase_support.creative")
__all__ = [name for name in dir(_TARGET) if not name.startswith("_")]


def __getattr__(name: str):
    return getattr(_TARGET, name)
