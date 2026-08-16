"""LibLib.tv (libtv) 客户端解析逻辑测试(零网络)—— 从 agent-im 会话消息提取结果 URL。"""

from __future__ import annotations

import json

from hevi.video.libtv_service import extract_result_urls


def test_extract_from_tool_task_result():
    """tool 消息的 task_result.images/videos 的 previewPath 被提取。"""
    tool_content = json.dumps(
        {
            "task_result": {
                "images": [{"previewPath": "https://libtv-res.liblib.art/a/1.png"}],
                "videos": [
                    {"previewPath": "https://libtv-res.liblib.art/a/v1.mp4"},
                    {"url": "https://libtv-res.liblib.art/a/v2.mp4"},  # 无 previewPath 退回 url
                ],
            }
        }
    )
    urls = extract_result_urls([{"role": "tool", "content": tool_content}])
    assert urls == [
        "https://libtv-res.liblib.art/a/1.png",
        "https://libtv-res.liblib.art/a/v1.mp4",
        "https://libtv-res.liblib.art/a/v2.mp4",
    ]


def test_extract_from_assistant_text_regex():
    """assistant 文本里的 libtv-res URL 被正则提取(带非 libtv 的 URL 不误取)。"""
    content = (
        "生成好啦!视频在 https://libtv-res.liblib.art/x/final.mp4 图 "
        "https://libtv-res.liblib.art/x/cover.png ,项目 https://www.liblib.tv/canvas?projectId=z"
    )
    urls = extract_result_urls([{"role": "assistant", "content": content}])
    assert urls == [
        "https://libtv-res.liblib.art/x/final.mp4",
        "https://libtv-res.liblib.art/x/cover.png",
    ]  # canvas 链接不是结果资源,不取


def test_dedup_order_and_ignore_user_msgs():
    """保序去重;user 消息 + 非字符串 content 忽略。"""
    msgs = [
        {"role": "user", "content": "生一个视频"},
        {"role": "assistant", "content": "https://libtv-res.liblib.art/d/1.mp4"},
        {"role": "assistant", "content": "https://libtv-res.liblib.art/d/1.mp4 重复"},
        {"role": "assistant", "content": None},
        {"role": "assistant", "content": "https://libtv-res.liblib.art/d/2.png"},
    ]
    assert extract_result_urls(msgs) == [
        "https://libtv-res.liblib.art/d/1.mp4",
        "https://libtv-res.liblib.art/d/2.png",
    ]


def test_malformed_tool_content_does_not_crash():
    """tool 消息 content 不是合法 JSON → 跳过不炸。"""
    assert extract_result_urls([{"role": "tool", "content": "not-json{"}]) == []
