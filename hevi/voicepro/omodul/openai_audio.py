"""Deprecated compatibility shim; canonical HEVI implementation is Layer4-owned."""

from hevi.layer4_legacy.voicepro.omodul_impl.openai_audio import *  # noqa: F403, I001
from hevi.layer4_legacy.voicepro.omodul_impl.openai_audio import get_engine  # type: ignore[attr-defined] # noqa: F401
