#!/usr/bin/env python3
"""step2_full_pipeline.py — E2E 全链路真跑 (1-5min 视频完整管线).

通过 REST API 触发全链路,轮询 SSE 进度,验证最终产物。
需要 hevi API 服务已启动: uv run uvicorn hevi.api.main:app

Usage:
    uv run python scripts/e2e/step2_full_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ── 资源检查 ─────────────────────────────────────────────────────────────────

_REQUIRED_F1 = {
    "FAL_API_KEY": "fal.ai API key",
    "DATABASE_URL": "PostgreSQL 连接串",
    "MINIO_ACCESS_KEY": "MinIO access key",
    "MINIO_SECRET_KEY": "MinIO secret key",
}


def _check_resources() -> None:
    missing = [k for k, _ in _REQUIRED_F1.items() if not os.getenv(k, "").strip()]
    if missing:
        for key in missing:
            print(f"[E2E] ❌ 缺少: {key} ({_REQUIRED_F1[key]})")
        print("      请参考 docs/E2E_SETUP.md")
        sys.exit(1)


# ── Step 2.1: REST API 触发长视频任务 ────────────────────────────────────────


async def trigger_pipeline(api_base: str) -> str:
    """POST /api/tasks/longvideo to trigger a pipeline. Returns task_id."""
    try:
        import httpx
    except ImportError:
        print("[step2.1] ❌ httpx 未安装: uv add httpx")
        sys.exit(1)

    payload = {
        "topic": "宇宙探险家发现外星文明",
        "duration_archetype": "medium",
        "video_provider": "fal_ltx2",
        "audio_provider": "vibevoice",
        "style": "sci-fi cinematic",
        "language": "zh",
        "num_characters": 1,
    }

    print(f"[step2.1] POST {api_base}/api/tasks/longvideo")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{api_base}/api/tasks/longvideo", json=payload)
        resp.raise_for_status()
        data = resp.json()

    task_id: str = data.get("task_id", data.get("id", ""))
    print(f"[step2.1] ✓ task_id={task_id!r} status={data.get('status')!r}")
    return task_id


# ── Step 2.2: SSE 进度轮询 ───────────────────────────────────────────────────


async def poll_sse_progress(api_base: str, task_id: str, timeout_s: float = 600.0) -> str:
    """Stream SSE progress events until completed/failed. Returns final status."""
    try:
        import httpx
    except ImportError:
        print("[step2.2] ❌ httpx 未安装")
        sys.exit(1)

    url = f"{api_base}/api/tasks/{task_id}/progress"
    print(f"[step2.2] SSE 轮询: {url}")
    deadline = time.monotonic() + timeout_s
    status = "unknown"

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if time.monotonic() > deadline:
                    print("[step2.2] ⚠ SSE timeout")
                    break
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                pct = event.get("progress_pct", 0)
                msg = event.get("message", "")
                status = event.get("status", status)
                print(f"[step2.2] {pct:3.0f}% {status} — {msg}")
                if status in ("completed", "failed"):
                    break

    print(f"[step2.2] ✓ 最终状态: {status!r}")
    return status


# ── Step 2.3: 产物验证 ───────────────────────────────────────────────────────


async def verify_output(api_base: str, task_id: str) -> None:
    """GET /api/tasks/{task_id} and verify result contains video_path."""
    try:
        import httpx
    except ImportError:
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{api_base}/api/tasks/{task_id}")
        if resp.status_code != 200:
            print(f"[step2.3] ⚠ task GET 返回 {resp.status_code}")
            return
        task = resp.json()

    video_path = task.get("result", {}).get("video_path", "")
    duration_s = task.get("result", {}).get("duration_s", 0)
    shots = task.get("result", {}).get("shots_count", 0)
    print("[step2.3] ✓ 产物验证:")
    print(f"          video_path = {video_path!r}")
    print(f"          duration_s = {duration_s}")
    print(f"          shots      = {shots}")

    if not video_path:
        print("[step2.3] ❌ video_path 为空 — 任务未成功完成")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("[step2] E2E 全链路真跑 — 1-5min 视频完整管线")
    print("=" * 60)

    _check_resources()

    api_base = os.getenv("HEVI_API_BASE", "http://localhost:8000")
    print(f"[step2] API: {api_base}")

    task_id = await trigger_pipeline(api_base)
    final_status = await poll_sse_progress(api_base, task_id)

    if final_status == "failed":
        print("[step2] ❌ 任务失败 — 检查 API 日志")
        sys.exit(1)

    await verify_output(api_base, task_id)

    print()
    print("[step2] ✓ 全链路 E2E 完成")
    print()
    print("→ 继续: uv run python scripts/e2e/step4_resilience.py")


if __name__ == "__main__":
    asyncio.run(main())
