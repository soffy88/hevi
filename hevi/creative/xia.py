"""hevi.creative.xia — Xia 对话式制片助理(对标 DramaClaw Xia)。

对话式制片助手:用户用自然语言提制片需求(改脚本/生成三视图/出分镜/查进度),
Xia 做意图路由 + 工具分发(绑定既有 AssistService/WorkflowService 操作),
保持会话上下文,产物引用回填。纯机制:会话状态机 + 意图路由 + 工具注册表,
装配层(API 路由)把具体操作注入。

意图分类为确定性关键词路由(不依赖 LLM,快速稳定),兜底走制片知识问答。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

# 工具契约: async (params: dict) -> dict(结果)
Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# 确定性意图路由: 关键词 → 工具名
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "three_view": ["三视图", "三面图", "角色设定图", "参考图"],
    "storyboard": ["分镜", "镜头脚本", "画面描述"],
    "story_predict": ["剧情预测", "后续剧情", "接下来会"],
    "multi_angle": ["多角度", "多机位", "机位角度"],
    "transition": ["首尾帧", "过渡", "转场"],
    "video_edit": ["视频编辑", "替换片段", "插入片段", "删除片段"],
    "character_consistency": ["角色一致性", "形象一致", "脸一致"],
    "comic_to_animation": ["漫画转", "漫画变动画", "动起来"],
    "multi_shot_storyboard": ["多镜头", "分镜工作流", "多格"],
    "screenplay": ["剧本", "改剧本", "分场", "脚本"],
    "dub": ["配音", "情感配音", "配声音"],
    "progress": ["进度", "到哪了", "到哪一步", "完成了吗"],
}

_FALLBACK_INTENT = "ask"  # 制片知识问答(LLM 兜底)


@dataclass
class XiaMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class XiaSession:
    """会话上下文: 多轮对话 + 已引用制片产物。"""

    session_id: str = field(default_factory=lambda: f"xia_{uuid4().hex[:12]}")
    messages: list[XiaMessage] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)  # 产物引用回填

    def add(self, role: str, content: str) -> None:
        self.messages.append(XiaMessage(role=role, content=content))
        if len(self.messages) > 50:  # 上下文截断,防无限膨胀
            self.messages = self.messages[-50:]


def route_intent(text: str) -> str:
    """确定性意图路由: 关键词命中 → 工具名; 否则 ask。"""
    for intent, kws in _INTENT_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return intent
    return _FALLBACK_INTENT


class XiaAssistant:
    """对话式制片助理: 意图路由 + 工具分发 + 会话保持。

    装配: register("storyboard", fn) 把 AssistService/WorkflowService
    的操作绑定进来; 未绑定的意图走 _fallback(制片问答/说明)。
    """

    def __init__(
        self,
        *,
        tools: dict[str, Tool] | None = None,
        fallback: Callable[[str, XiaSession], Awaitable[str]] | None = None,
        llm: Any = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        if tools:
            for name, fn in tools.items():
                self.register(name, fn)
        self._fallback = fallback
        self._llm = llm
        self._sessions: dict[str, XiaSession] = {}

    def register(self, name: str, fn: Tool) -> None:
        self._tools[name] = fn

    def get_session(self, session_id: str | None = None) -> XiaSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        s = XiaSession(session_id=session_id or "")
        self._sessions[s.session_id] = s
        return s

    async def chat(self, text: str, session_id: str | None = None) -> dict[str, Any]:
        """单轮对话: 意图路由 → 工具调用(或问答) → 回复 + 会话更新。"""
        session = self.get_session(session_id)
        session.add("user", text)
        intent = route_intent(text)

        tool = self._tools.get(intent)
        if tool is not None:
            try:
                result = await tool({"text": text, "session": session})
                reply = self._render_tool_reply(intent, result)
                session.artifacts[f"last_{intent}"] = result
            except Exception as exc:
                reply = f"这个操作我没能完成:{exc}。可以换个说法,或先问我制片知识。"
        elif self._fallback is not None:
            reply = await self._fallback(text, session)
        else:
            reply = self._default_fallback(text)
        session.add("assistant", reply)
        return {
            "session_id": session.session_id,
            "intent": intent,
            "reply": reply,
            "tool": intent if intent in self._tools else None,
        }

    @staticmethod
    def _render_tool_reply(intent: str, result: dict[str, Any]) -> str:
        """工具结果 → 自然语言回复(确定性模板,不调 LLM)。"""
        if intent == "progress":
            return f"当前进度:{result.get('message', '')}"
        summary = result.get("summary") or result.get("message") or ""
        detail = ""
        if result.get("shots") is not None:
            detail = f" 共 {len(result['shots'])} 个镜头。"
        if result.get("outputs") is not None:
            detail = f" 产物:{result['outputs']}"
        return f"{summary or '完成'}。{detail}".strip() or "已完成。"

    @staticmethod
    def _default_fallback(text: str) -> str:
        return (
            f"我是 Xia,你的制片助理。我可以:生成三视图/分镜、剧情预测、"
            f"多角度提示、首尾帧过渡、视频编辑、角色一致性、漫画转动画、"
            f"改剧本、情感配音、查进度。你说「{text[:20]}」我暂时没识别到具体操作,"
            f"可以换个说法试试。"
        )
