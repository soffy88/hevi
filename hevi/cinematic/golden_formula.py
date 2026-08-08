"""golden_formula —— 黄金公式分镜拆解器 (演绎段动画化)。

用户范式 (视频 AI 提示词黄金公式):
    [景别/运镜] + [主体 + 动作 + 表情/肢体] + [氛围/光线]

把干瘪的历史故事切成 3-5s 的矩阵节点 (GoldenBeat), 每格填充结构化变量
(shot_size/movement/subject/action/emotion_expression/atmosphere/lighting),
拼装成两种消费形态:
    a) shot prompt (接 shot_planning / 直接喂视频大模型 API)
    b) CineShot 列表 (接 C6 动画分支, 复用降级链, 无人脸参考图)

"把情绪变成视觉动作, 把重点变成专业运镜" —— emotion 一律降维为可渲染的
物理参数 (表情/肢体), 不在 prompt 里留抽象词 (AI 听不懂"开心"/"害怕")。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 黄金公式镜头时长区间 (秒)
MIN_BEAT_S = 3.0
MAX_BEAT_S = 5.0


@dataclass
class GoldenBeat:
    """一个 3-5s 分镜矩阵节点。"""

    index: int
    shot_size: str = "medium"          # 景别: wide/full/medium/medium_close/close/extreme_close
    movement: str = "static"           # 运镜: static/pan/tilt/push_in/pull_out/tracking
    subject: str = ""                  # 主体
    action: str = ""                   # 主动作
    emotion_expression: str = ""       # 情绪反应 (表情/肢体, 视觉动作化)
    atmosphere: str = ""               # 氛围
    lighting: str = ""                 # 光线
    duration_s: float = 4.0            # 3-5s
    narration: str = ""                # 该镜旁白 (可选)

    @property
    def shot_prompt(self) -> str:
        """黄金公式拼装: [景别/运镜] + [主体+动作+表情] + [氛围/光线]。"""
        camera = f"{self.shot_size}, {self.movement}" if self.movement != "static" \
            else self.shot_size
        subject = f"{self.subject}" if self.subject else ""
        action = f", {self.action}" if self.action else ""
        expression = f", {self.emotion_expression}" if self.emotion_expression else ""
        env = "、".join(x for x in (self.atmosphere, self.lighting) if x)
        env_part = f", {env}" if env else ""
        return f"{camera}, {subject}{action}{expression}{env_part}".strip(" ,")

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "shot_size": self.shot_size,
                "movement": self.movement, "subject": self.subject,
                "action": self.action, "emotion_expression": self.emotion_expression,
                "atmosphere": self.atmosphere, "lighting": self.lighting,
                "duration_s": self.duration_s, "narration": self.narration,
                "shot_prompt": self.shot_prompt}


_DECOMPOSE_SYSTEM = """你是历史短片的分镜导演。把输入的故事切成 3-5 秒的镜头矩阵, 每镜严格按
黄金公式填充结构化字段: [景别/运镜] + [主体+动作+表情/肢体] + [氛围/光线]。

铁律:
1. 时长 3-5s, 全片总时长≈输入时长的合理叙事节奏;
2. 情绪必须降维成视觉动作: 不写"开心"/"害怕", 写"嘴角上扬欢笑"/"双手乱抓、双眼张大";
3. 每个字段都填, 没信息时用合理的电影化推断 (允许虚构细节, 不得改变史实因果);
4. 只输出 JSON 数组, 不要任何解释文字。

输出格式 (JSON 数组, 字段名必须是英文, 完整示例):
[{"shot_size": "medium", "movement": "pan", "subject": "司马光",
  "action": "在庭院里跑跳追逐", "emotion_expression": "嘴角上扬欢笑",
  "atmosphere": "轻松嬉戏", "lighting": "明亮日光",
  "duration_s": 3.0, "narration": "古代小孩在庭院中嬉戏"}]

字段含义: shot_size(景别: wide/full/medium/medium_close/close/extreme_close),
movement(运镜: static/pan/tilt/push_in/pull_out/tracking),
subject(主体), action(主动作), emotion_expression(情绪反应=表情/肢体, 必须视觉化),
atmosphere(氛围), lighting(光线), duration_s(3-5), narration(该镜旁白解说)。
"""



async def decompose_story_to_golden_beats(
    story: str,
    llm: Any,
    *,
    max_beats: int = 8,
) -> list[GoldenBeat]:
    """LLM 按黄金公式把故事切成分镜矩阵。

    llm 接口自适应 (registry 约定: `await llm(messages=...) -> dict(content=...)`;
    或旧式 `llm.chat(messages) -> str`, 同步/异步均可)。

    注意: 必须在已运行的事件循环里直接 await, 不能 run_until_complete
    (FastAPI 后台任务里会抛 "event loop already running")。
    """
    user = f"故事: {story}\n\n最多 {max_beats} 镜, 每镜 3-5s, 输出 JSON 数组。"
    messages = [
        {"role": "system", "content": _DECOMPOSE_SYSTEM},
        {"role": "user", "content": user},
    ]
    raw = await _llm_text(llm, messages)
    return parse_golden_beats(raw, max_beats=max_beats)


async def _llm_text(llm: Any, messages: list[dict[str, str]]) -> str:
    """统一 LLM 文本输出: 支持 registry async 约定 与 chat()/可调用 多种形态。"""
    import inspect

    try:
        if hasattr(llm, "chat"):
            out = llm.chat(messages)
            if inspect.isawaitable(out):
                out = await out
        else:
            out = llm(messages=messages)
            if inspect.isawaitable(out):
                out = await out
    except Exception as exc:
        logger.warning("黄金公式 LLM 调用失败: %s", exc)
        return ""
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        content = out.get("content") or ""
        if not content:
            choices = (out.get("output") or {}).get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
        return str(content)
    return str(out)


def parse_golden_beats(raw: str, *, max_beats: int = 8) -> list[GoldenBeat]:
    """解析 LLM 输出 (容忍代码块/前后噪声) → GoldenBeat 列表。失败返回空。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("黄金公式解析失败: 无 JSON 数组 (%.80s…)", raw)
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("黄金公式 JSON 解析失败: %s", exc)
        return []
    beats: list[GoldenBeat] = []
    for i, item in enumerate(data[:max_beats]):
        if not isinstance(item, dict):
            continue
        # 兼容中/英文键 (deepseek 等模型常输出中文键: 镜头/时长/画面/景别…)
        v = lambda *keys: next((item.get(k) for k in keys if item.get(k) is not None), None)
        try:
            dur = float(v("duration_s", "时长", "duration") or MAX_BEAT_S)
            dur = max(MIN_BEAT_S, min(MAX_BEAT_S, dur))
        except (TypeError, ValueError):
            dur = MAX_BEAT_S
        scene_text = str(v("画面", "content", "text") or "")
        subject = str(v("subject", "主体", "主角", "角色") or "")
        action = str(v("action", "动作", "主动作") or "")
        # 画面字段可包含完整视觉描述 → 并入 action (若 action 空)
        if scene_text and not action:
            action = scene_text
        beats.append(GoldenBeat(
            index=i,
            shot_size=str(v("shot_size", "景别", "景別") or "medium"),
            movement=str(v("movement", "运镜", "镜头运动") or "static"),
            subject=subject,
            action=action,
            emotion_expression=str(v("emotion_expression", "表情", "情绪反应", "情绪") or ""),
            atmosphere=str(v("atmosphere", "氛围", "气氛") or ""),
            lighting=str(v("lighting", "光线", "灯光", "光") or ""),
            duration_s=dur,
            # 旁白缺失 → 用画面描述兜底 (有解说比没强, TTS 不接受空文本)。
            narration=str(v("narration", "旁白", "解说", "台词", "文案")
                          or scene_text or action or subject),
        ))
    return beats


def golden_beats_to_shot_prompts(beats: list[GoldenBeat]) -> list[str]:
    """批量喂视频 API 的 prompt 矩阵 (用户流水线的\"批量生成\"步)。"""
    return [b.shot_prompt for b in beats]


__all__ = [
    "MAX_BEAT_S",
    "MIN_BEAT_S",
    "GoldenBeat",
    "decompose_story_to_golden_beats",
    "golden_beats_to_shot_prompts",
    "parse_golden_beats",
]
