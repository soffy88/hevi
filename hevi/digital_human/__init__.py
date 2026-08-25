"""Digital-human 能力域(3O §3 Task 3.2 收拢)。

    models.py          # Presenter 配置面模型(自 hevi/presenters 迁入)
    duix_service.py    # DUIX 直播服务边界
    avatar_render.py   # 通用云数字人渲染服务(自 tongjian/scene_render_avatar.py 抽离)
    lipsync_driver.py  # 口型与音频同步驱动(oskill 边界)
    talking_face.py    # 🚨 v9.0: 全时段 Talking Face 底轨生成(LongCat/EchoMimic)

    # 3O §3 Task 3.4: Presenter-Video 完整工作流
    schemas.py         # Job/JobStatus/TimelinePlan/CaptionPlan/QAReport 契约
    oprim/             # 原子: narration/timeline/caption/qa/render
    oskill/            # 技能: content_lock/visual_plan/caption_plan/generate_presenter/delivery/qa_gate
    omodul/            # 规划: init_job/plan_*_phase/build_full_job_plan

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
from hevi.digital_human.omodul import (
    build_full_job_plan,
    execute_plan,
    init_job,
    plan_composition,
    plan_delivery,
    plan_generation,
    plan_presenter_generation,
    plan_visual,
)
from hevi.digital_human.oprim import (
    add_clip_to_timeline,
    build_timeline,
    calibrate_audio_loudness,
    generate_narration,
    lock_content,
    run_preflight_check,
    run_qa_gate,
)
from hevi.digital_human.oskill import (
    caption_plan,
    content_lock,
    delivery,
    generate_presenter,
    preflight_check,
    qa_gate,
    visual_plan,
)

# 3O 层导出
from hevi.digital_human.schemas import (
    AudioMeasurement,
    CaptionPhrase,
    CaptionPlan,
    ChapterSpec,
    ClipSpec,
    JobPriority,
    JobStatus,
    PresenterJob,
    QAReport,
    TimelinePlan,
    make_default_caption_plan,
    make_default_job,
    make_default_qa_report,
    make_default_timeline,
)
from hevi.digital_human.talking_face import (
    TalkingFaceUnavailable,
    generate_continuous_avatar_track,
    generate_talking_face,
)

__all__ = [
    "AudioMeasurement",
    "CaptionPhrase",
    "CaptionPlan",
    "ChapterSpec",
    "ClipSpec",
    # 原有导出
    "DuixLiveService",
    "DuixUnavailable",
    "JobPriority",
    "JobStatus",
    "LipSyncCapability",
    "LipSyncUnsupported",
    "Presenter",
    # 3O 新增导出
    "PresenterJob",
    "QAReport",
    "TalkingFaceUnavailable",
    "TimelinePlan",
    "add_clip_to_timeline",
    "build_full_job_plan",
    "build_timeline",
    "calibrate_audio_loudness",
    "caption_plan",
    "concat_clips",
    "content_lock",
    "delivery",
    "drive_lip_sync",
    "ensure_lip_sync",
    "execute_plan",
    "extract_frame",
    "fit_dialogue_clip",
    "fit_narration_clip",
    "fit_silent_clip",
    "generate_continuous_avatar_track",
    "generate_narration",
    "generate_presenter",
    "generate_talking_face",
    "init_job",
    "lip_sync_capability",
    "lock_content",
    "make_default_caption_plan",
    "make_default_job",
    "make_default_qa_report",
    "make_default_timeline",
    "plan_composition",
    "plan_delivery",
    "plan_generation",
    "plan_presenter_generation",
    "plan_visual",
    "preflight_check",
    "probe_duration",
    "qa_gate",
    "resolve_dimensions",
    "run_preflight_check",
    "run_qa_gate",
    "score_consistency",
    "visual_plan",
]
