"""JoyAI-style streaming video editing contracts (lazy compatibility API)."""

from importlib import import_module

_EXPORTS = {
    name: "hevi.layer4_legacy.joyai.omodul_impl.stream_edit"
    for name in (
        "capabilities", "create_session", "finish_session", "get_session", "list_sessions",
        "record_frame", "record_output", "reset_sessions", "start_session", "stream_provider_url",
    )
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name), name)

__all__ = [
    "capabilities",
    "create_session",
    "finish_session",
    "get_session",
    "list_sessions",
    "record_frame",
    "record_output",
    "reset_sessions",
    "start_session",
    "stream_provider_url",
]
