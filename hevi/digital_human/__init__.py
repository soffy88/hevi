"""Digital-human 能力域(3O §3 Task 3.2 收拢)。

    models.py          # Presenter 配置面模型(自 hevi/presenters 迁入)
    duix_service.py    # DUIX 直播服务边界
    avatar_render.py   # 通用云数字人渲染服务(自 tongjian/scene_render_avatar.py 抽离)
    lipsync_driver.py  # 口型与音频同步驱动(oskill 边界)
    talking_face.py    # 🚨 v9.0: 全时段 Talking Face 底轨生成(LongCat/EchoMimic)

对外的 hevi.presenters 保持兼容 shim(零回归迁移)。
"""

from hevi.digital_human.avatar_render import (
    concat_clips,
    extract_frame,
    fit_dialogue_clip,
    fit_narration_clip,
    fit_silent_clip,
    probe_duration,
    resolve_dimensions,
    score_consistency,
)
from hevi.digital_human.duix_service import DuixLiveService, DuixUnavailable
from hevi.digital_human.lipsync_driver import (
    LipSyncCapability,
    LipSyncUnsupported,
    drive_lip_sync,
    ensure_lip_sync,
    lip_sync_capability,
)
from hevi.digital_human.models import Presenter
from hevi.digital_human.talking_face import (
    TalkingFaceUnavailable,
    generate_continuous_avatar_track,
    generate_talking_face,
)

__all__ = [
    "DuixLiveService",
    "DuixUnavailable",
    "LipSyncCapability",
    "LipSyncUnsupported",
    "Presenter",
    "TalkingFaceUnavailable",
    "concat_clips",
    "drive_lip_sync",
    "ensure_lip_sync",
    "extract_frame",
    "fit_dialogue_clip",
    "fit_narration_clip",
    "fit_silent_clip",
    "generate_continuous_avatar_track",
    "generate_talking_face",
    "lip_sync_capability",
    "probe_duration",
    "resolve_dimensions",
    "score_consistency",
]
