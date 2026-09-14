"""导演层:照片锁身份。实现在 hevi.script2video。"""

from hevi.layer4_legacy.script2video.omodul_impl.cameo_plan import plan_autocameo
from hevi.production.autocameo_workflow import (
    AutoCameoConfig,
    AutoCameoInput,
    autocameo_workflow,
)
from hevi.script2video.adapter_schemas import CameoCharacter, CameoPlan, PersonInfo

__all__ = [
    "AutoCameoConfig",
    "AutoCameoInput",
    "CameoCharacter",
    "CameoPlan",
    "PersonInfo",
    "autocameo_workflow",
    "plan_autocameo",
]
