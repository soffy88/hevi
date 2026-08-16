from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from oprim.character_three_view import ThreeViewResult, character_three_view
from oprim.first_last_frame_transition import first_last_frame_transition
from oprim.multi_angle import MultiAngleResult, multi_angle
from oprim.story_predict import StoryPrediction, story_predict
from oprim.storyboard_grid import StoryboardGridResult, storyboard_grid
from oprim.video_element_edit import video_element_edit


def _strip_markdown_json(content: str) -> str:
    """剥掉 LLM 输出中的 ```json 代码块包裹, 返回纯 JSON 文本。"""
    import re

    text = content.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


_VALID_OPERATIONS: frozenset[str] = frozenset({"replace", "insert", "delete"})


class AssistService:
    """Business layer — 6 oprim creative assist operations."""

    def __init__(self, caller: Any = None, llm: Any = None) -> None:
        self._caller = caller
        self._llm = llm

    def _resolve_caller(self) -> Any:
        """优先注入的 caller; 缺省回退全局 ProviderRegistry 默认 LLM。

        v9.1 修复: 之前 caller=None 时 oprim 直接 `await caller(...)` 抛
        "NoneType' object is not callable"——MCP/Canvas 直调路径不可读。
        现在回退 API 启动时注册的 NIM/dashscope 默认 LLM; 两者皆无则抛
        带指引的错误(而非 NoneType)。
        """
        if self._caller is not None:
            return self._caller
        try:
            from obase.provider_registry import ProviderRegistry

            reg = ProviderRegistry.get()
            # 优先 NIM(研究同源, 本机可用); 其次 default(dashscope)。
            # 旧版 obase 未注册时 reg.llm() 返回 None 而不抛异常 →
            # 直接 return None 会让 oprim `await caller(...)` 抛
            # "NoneType' object is not callable" — 此处显式校验。
            for name in ("nim", "default"):
                try:
                    caller = reg.llm(name)
                    if caller is not None:
                        return caller
                except Exception:
                    continue
            raise ProviderRegistry.ProviderNotFoundError(  # type: ignore[attr-defined]
                "no llm provider registered"
            )
        except Exception as exc:
            raise RuntimeError(
                "AssistService caller 未注入且全局 LLM provider 未注册; "
                "请经 API 边界调用(register_all_providers 会注册 NIM/dashscope) "
                "或显式注入 caller。"
            ) from exc

    def _wrapped_caller(self) -> Any:
        """LLM 输出健壮性包装: 剥 markdown ```json 代码块。

        NIM fallback 模型常返回 ```json...``` 包裹的 JSON, oprim 的
        json.loads 直接解析会失败(此前 gen_storyboard 报
        "invalid JSON from LLM")。包装层在交给 oprim 前清理 content。
        """
        base = self._resolve_caller()

        async def _wrapped(**kwargs: Any) -> dict[str, Any]:
            response = await base(**kwargs)
            content = response.get("content")
            # oprim storyboard_grid 期望 Anthropic block 列表
            # ([{"type": "text", "text": "..."}]); NIM/OpenCode/local 均返回
            # OpenAI 风格字符串 → 归一化, 否则 storyboard_grid 遍历字符串字符
            # 得到空文本 → "invalid JSON from LLM"。
            if isinstance(content, str):
                cleaned = _strip_markdown_json(content)
                response = {**response, "content": [{"type": "text", "text": cleaned}]}
            return dict(response)

        return _wrapped

    async def gen_three_view(
        self,
        *,
        character_description: str,
        style: str = "",
    ) -> ThreeViewResult:
        if not character_description.strip():
            raise ValueError("character_description must not be empty")
        return await character_three_view(
            character_description, caller=self._wrapped_caller(), style=style
        )

    async def gen_storyboard(
        self,
        *,
        script_text: str,
        shots: int = 6,
    ) -> StoryboardGridResult:
        if not script_text.strip():
            raise ValueError("script_text must not be empty")
        if shots < 1:
            raise ValueError("shots must be >= 1")
        return await storyboard_grid(script_text, caller=self._wrapped_caller(), shots=shots)

    async def predict_story(
        self,
        *,
        reference_image: Path,
        direction: Literal["forward", "backward", "both"],
        prediction_points: list[int] | None = None,
    ) -> StoryPrediction:
        return await story_predict(
            reference_image=reference_image,
            llm=self._llm,
            direction=direction,
            prediction_points=prediction_points,
        )

    async def gen_multi_angle(
        self,
        *,
        subject_description: str,
        angles: list[str] | None = None,
    ) -> MultiAngleResult:
        if not subject_description.strip():
            raise ValueError("subject_description must not be empty")
        return await multi_angle(
            subject_description, caller=self._wrapped_caller(), angles=angles
        )

    async def make_transition(
        self,
        *,
        first_frame: Path,
        last_frame: Path,
        duration_s: float,
        video_provider: str,
        output_path: Path,
    ) -> Path:
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        return await first_last_frame_transition(
            first_frame=first_frame,
            last_frame=last_frame,
            duration_s=duration_s,
            video_provider=video_provider,
            output_path=output_path,
        )

    async def edit_video_elements(
        self,
        *,
        elements: list[dict[str, Any]],
        operation: str,
        target_index: int,
        replacement: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if operation not in _VALID_OPERATIONS:
            raise ValueError(
                f"operation must be one of {sorted(_VALID_OPERATIONS)}, got {operation!r}"
            )
        if operation in {"replace", "insert"} and replacement is None:
            raise ValueError(f"replacement is required for '{operation}' operation")
        raw = await video_element_edit(
            elements=elements,
            operation=operation,
            target_index=target_index,
            replacement=replacement,
            caller=self._wrapped_caller(),
        )
        return cast(list[dict[str, Any]], raw)
