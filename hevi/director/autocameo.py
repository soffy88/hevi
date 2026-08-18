"""导演层:照片锁身份。实现在 hevi.script2video。"""

from hevi.production.autocameo_workflow import (
    AutoCameoConfig,
    AutoCameoInput,
    autocameo_workflow,
)
from hevi.script2video.adapter_schemas import CameoCharacter, CameoPlan, PersonInfo
from hevi.script2video.omodul.cameo_plan import plan_autocameo

__all__ = [
    "AutoCameoConfig",
    "AutoCameoInput",
    "CameoCharacter",
    "CameoPlan",
    "PersonInfo",
    "autocameo_workflow",
    "plan_autocameo",
]
