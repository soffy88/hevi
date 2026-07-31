"""hevi L4 导演层 —— Producer / Director / Editor(设计 §3 L4)。

跑在已有件上,不新建管线:
  Producer(意图→约束+预算可行性)→ Director(分镜→**可执行 canvas 图**)→ 执行 →
  Editor(消费体检+评分卡→交付 or 定向返工)。
把 L0 路由 / L1 落库 / L3 体检+评分卡 / verdict→返工闭环 串成一个导演回路。
"""

from hevi.director.agent import DirectorResult, run_director_loop
from hevi.director.autocameo import AutoCameo, AutoCameoConfig, AutoCameoResult, CameoCharacter
from hevi.director.camera_tree import CameraNode, CameraTree, construct_camera_tree
from hevi.director.director import build_canvas_graph
from hevi.director.editor import DIAGNOSIS_CATEGORIES, EditDecision, review
from hevi.director.idea2video import Idea2VideoConfig, Idea2VideoPipeline, Idea2VideoResult
from hevi.director.image_selector import CandidateImage, SelectionResult, select_best_image
from hevi.director.intent import parse_intent
from hevi.director.novel2video import Novel2VideoConfig, Novel2VideoPipeline, Novel2VideoResult
from hevi.director.planner import plan_from_text
from hevi.director.portrait_triptych import (
    CharacterPortrait,
    PortraitRegistry,
    PortraitView,
    generate_all_portraits,
    generate_portrait_triptych,
)
from hevi.director.producer import ProducerPlan, produce
from hevi.director.render_backend import (
    RenderBackend,
    RenderBackendConfig,
    create_render_backend,
)
from hevi.director.storyboard import plan_shots
from hevi.director.transition_video import (
    TransitionResult,
    TransitionSpec,
    TransitionStrategy,
    bridge_shots,
    generate_transition_video,
)

__all__ = [
    "AutoCameo",
    "AutoCameoConfig",
    "AutoCameoResult",
    "CandidateImage",
    "CameoCharacter",
    "CameraNode",
    "CameraTree",
    "CharacterPortrait",
    "DIAGNOSIS_CATEGORIES",
    "DirectorResult",
    "EditDecision",
    "Idea2VideoConfig",
    "Idea2VideoPipeline",
    "Idea2VideoResult",
    "Novel2VideoConfig",
    "Novel2VideoPipeline",
    "Novel2VideoResult",
    "PortraitRegistry",
    "PortraitView",
    "ProducerPlan",
    "RenderBackend",
    "RenderBackendConfig",
    "create_render_backend",
    "SelectionResult",
    "TransitionResult",
    "TransitionSpec",
    "TransitionStrategy",
    "bridge_shots",
    "build_canvas_graph",
    "construct_camera_tree",
    "generate_all_portraits",
    "generate_portrait_triptych",
    "generate_transition_video",
    "parse_intent",
    "plan_from_text",
    "plan_shots",
    "produce",
    "review",
    "run_director_loop",
    "select_best_image",
]
