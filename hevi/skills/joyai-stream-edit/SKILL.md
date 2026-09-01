---
name: joyai-stream-edit
version: "0.1.0"
description: Causal live/upload video-to-video editing through a JoyAI-compatible WebSocket provider.
argument-hint: "capabilities | budget | create --prompt \"...\" | inspect --session <id>"
allowed-tools: Bash, Read
user-invocable: true
---

# /joyai-stream-edit

JoyAI 风格实时 V2V 技能。HEVI 只提交和审计真实帧流：实时编辑必须连接
`JOYAI_STREAM_WS_URL`，或者连接 `JOYAI_BASE_URL`（可用 `JOYAI_STREAM_WS_PATH`
覆盖默认 `/ws/edit`）。没有 Provider 时只返回 blocked session，不伪造输出。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.joyai_stream_edit_cli capabilities
uv run python -m hevi.skills.joyai_stream_edit_cli budget --width 840 --height 480 --fps 24
uv run python -m hevi.skills.joyai_stream_edit_cli create --prompt "把背景变成霓虹雨夜"
```

## 3O 约束

- `oprim`：控制消息、分辨率/FPS 边界、原始帧内存预算。
- `oskill`：把 live/upload、subject/local/background/style/motion/reference image
  意图编译成结构化会话请求。
- `omodul`：会话生命周期、Provider WebSocket 转发、输入/输出帧计数和决策轨迹。

客户端控制消息使用 JSON：`start`、`frame`、`heartbeat`、`end`；视频帧使用二进制
消息。HEVI 透传上游二进制响应并记录本地会话状态，不会把会话状态当成视频文件。
