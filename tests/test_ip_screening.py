"""IP 安全 pass —— 图像半边测试(HEVI 路线图 Phase2 #36)。"""

from __future__ import annotations

from unittest.mock import AsyncMock

from hevi.subjects.ip_screening import flag_if_recognizable_person


def _vlm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


async def test_no_vlm_returns_empty():
    assert await flag_if_recognizable_person("x.png", vlm=None) == []


async def test_unflagged_photo_returns_empty():
    vlm = _vlm('{"flagged": false, "reason": ""}')
    assert await flag_if_recognizable_person("x.png", vlm=vlm) == []


async def test_flagged_photo_returns_reason():
    vlm = _vlm('{"flagged": true, "reason": "疑似某知名演员"}')
    assert await flag_if_recognizable_person("x.png", vlm=vlm) == ["疑似某知名演员"]


async def test_flagged_without_reason_treated_as_unflagged():
    """flagged=true 但没给 reason(响应不完整)—— 没有可展示的说明就不算命中,
    不能返回空字符串占位。"""
    vlm = _vlm('{"flagged": true, "reason": ""}')
    assert await flag_if_recognizable_person("x.png", vlm=vlm) == []


async def test_malformed_response_returns_empty():
    vlm = _vlm("not json")
    assert await flag_if_recognizable_person("x.png", vlm=vlm) == []


async def test_vlm_exception_returns_empty():
    vlm = AsyncMock(side_effect=RuntimeError("vl model down"))
    assert await flag_if_recognizable_person("x.png", vlm=vlm) == []
