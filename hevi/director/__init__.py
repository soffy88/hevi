"""hevi L4 导演层 —— Producer / Director / Editor(设计 §3 L4)。

跑在已有件上,不新建管线:
  Producer(意图→约束+预算可行性)→ Director(分镜→**可执行 canvas 图**)→ 执行 →
  Editor(消费体检+评分卡→交付 or 定向返工)。
把 L0 路由 / L1 落库 / L3 体检+评分卡 / verdict→返工闭环 串成一个导演回路。
"""

from hevi.director.agent import DirectorResult, run_director_loop
from hevi.director.director import build_canvas_graph
from hevi.director.editor import DIAGNOSIS_CATEGORIES, EditDecision, review
from hevi.director.intent import parse_intent
from hevi.director.planner import plan_from_text
from hevi.director.producer import ProducerPlan, produce
from hevi.director.storyboard import plan_shots

__all__ = [
    "DIAGNOSIS_CATEGORIES",
    "DirectorResult",
    "EditDecision",
    "ProducerPlan",
    "build_canvas_graph",
    "parse_intent",
    "plan_from_text",
    "plan_shots",
    "produce",
    "review",
    "run_director_loop",
]
