"""RISO B-roll unit:孔版双色印刷风口播信息动画."""

from hevi.riso.capabilities import register_riso_capabilities
from hevi.riso.constants import PALETTES, TEMPLATE_NAMES
from hevi.riso.gatekeeper import (
    check_numbers_preserved,
    is_subsequence,
    validate_screen_content,
)
from hevi.riso.pipeline import (
    PipelineGateError,
    direct_render,
    run_gate1_storyboard,
    run_gate2_keyframes_and_qa,
    run_gate3_final_render,
)
from hevi.riso.proof_sheet import create_proof_sheet
from hevi.riso.qa import QAReport, run_qa_checks
from hevi.riso.render import (
    FontLoadError,
    RisoRenderError,
    WebRenderSession,
    compute_image_psnr,
    extract_video_last_frame,
    render_clip,
)
from hevi.riso.storyboard import StoryboardPlan, StoryboardShot, generate_storyboard

# Automatically register capabilities on package import
register_riso_capabilities()

__all__ = [
    "FontLoadError",
    "PALETTES",
    "PipelineGateError",
    "QAReport",
    "RisoRenderError",
    "StoryboardPlan",
    "StoryboardShot",
    "TEMPLATE_NAMES",
    "WebRenderSession",
    "check_numbers_preserved",
    "compute_image_psnr",
    "create_proof_sheet",
    "direct_render",
    "extract_video_last_frame",
    "generate_storyboard",
    "is_subsequence",
    "register_riso_capabilities",
    "render_clip",
    "run_gate1_storyboard",
    "run_gate2_keyframes_and_qa",
    "run_gate3_final_render",
    "run_qa_checks",
    "validate_screen_content",
]
