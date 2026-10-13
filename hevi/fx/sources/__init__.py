"""FX template sources — parsers for each origin system."""

from hevi.fx.sources.sfx import load_sfx
from hevi.fx.sources.talkcraft import load_talkcraft
from hevi.fx.sources.xfade import load_xfade

__all__ = ["load_sfx", "load_talkcraft", "load_xfade"]