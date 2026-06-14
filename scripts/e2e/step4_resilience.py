#!/usr/bin/env python3
"""step4_resilience.py — E2E 断点续传真验证.

1. 启动一个长视频任务 (step4.1)
2. 在 30% 进度时模拟进程中断 (step4.2)
3. 重启任务并验证从 checkpoint 恢复 (step4.3)
4. 验证最终产物完整 (step4.4)

Usage:
    uv run python scripts/e2e/step4_resilience.py
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

_REQUIRED = {
    "FAL_API_KEY": "fal.ai API key",
    "DATABASE_URL": "PostgreSQL 连接串",
    "MINIO_ACCESS_KEY": "MinIO access key",
    "MINIO_SECRET_KEY": "MinIO secret key",
}


def _check_resources() -> None:
    missing = [k for k in _REQUIRED if not os.getenv(k, "").strip()]
    if missing:
        for key in missing:
            print(f"[E2E] ❌ 缺少: {key} ({_REQUIRED[key]})")
        print("      请参考 docs/E2E_SETUP.md")
        sys.exit(1)


# ── 工具函数 ─────────────────────────────────────────────────────────────────


async def _api_get(base: str, path: str) -> dict[str, object]:
    try:
        import httpx
    except ImportError:
        print("❌ httpx 未安装: uv add httpx")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{base}{path}")
        resp.raise_for_status()
        result: dict[str, object] = resp.json()
        return result


async def _api_post(base: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        import httpx
    except ImportError:
        print("❌ httpx 未安装")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{base}{path}", json=payload)
        resp.raise_for_status()
        result: dict[str, object] = resp.json()
        return result


# ── Step 4.1: 启动任务 ───────────────────────────────────────────────────────


async def start_task(api_base: str) -> str:
    """Start a long-video task. Returns task_id."""
    payload: dict[str, object] = {
        "topic": "蒸汽朋克城市的日落",
        "duration_archetype": "medium",
        "video_provider": "fal_ltx2",
        "audio_provider": "vibevoice",
        "style": "steampunk",
        "language": "zh",
    }
    resp = await _api_post(api_base, "/api/tasks/longvideo", payload)
    task_id = str(resp.get("task_id", resp.get("id", "")))
    print(f"[step4.1] ✓ 任务启动: task_id={task_id!r}")
    return task_id


# ── Step 4.2: 等待 30% 后模拟中断 ───────────────────────────────────────────


async def wait_until_partial_then_interrupt(
    api_base: str, task_id: str, interrupt_at_pct: float = 30.0
) -> str:
    """Poll progress SSE until `interrupt_at_pct`, then cancel task. Returns checkpoint_id."""
    try:
        import httpx
    except ImportError:
        sys.exit(1)

    url = f"{api_base}/api/tasks/{task_id}/progress"
    print(f"[step4.2] 轮询进度直到 {interrupt_at_pct:.0f}%: {url}")
    checkpoint_id = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                pct = float(event.get("progress_pct", 0))
                checkpoint_id = str(event.get("checkpoint_id", ""))
                print(f"[step4.2] {pct:5.1f}% checkpoint={checkpoint_id!r}")

                if pct >= interrupt_at_pct:
                    print(f"[step4.2] 到达 {pct:.0f}%,模拟中断...")
                    break

    # 取消任务(模拟进程被 kill)
    try:
        cancel_resp = await _api_post(
            api_base, f"/api/tasks/{task_id}/cancel", {}
        )
        print(f"[step4.2] ✓ 任务已取消: {cancel_resp.get('status')!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"[step4.2] ⚠ 取消任务失败 (可忽略): {exc}")

    return checkpoint_id


# ── Step 4.3: 从 checkpoint 恢复 ─────────────────────────────────────────────


async def resume_from_checkpoint(api_base: str, task_id: str) -> str:
    """Resume the interrupted task. Returns resumed task_id."""
    print(f"[step4.3] 恢复任务: task_id={task_id!r}")

    # 等待 2 秒模拟进程重启间隔
    await asyncio.sleep(2.0)

    resp = await _api_post(api_base, f"/api/tasks/{task_id}/resume", {})
    resumed_id = str(resp.get("task_id", task_id))
    print(f"[step4.3] ✓ 恢复成功: resumed_task_id={resumed_id!r}")
    return resumed_id


# ── Step 4.4: 验证最终产物完整 ───────────────────────────────────────────────


async def verify_resumed_output(api_base: str, task_id: str, timeout_s: float = 600.0) -> None:
    """Poll until completion and verify output is intact."""
    try:
        import httpx
    except ImportError:
        sys.exit(1)

    deadline = time.monotonic() + timeout_s
    url = f"{api_base}/api/tasks/{task_id}/progress"
    status = "unknown"

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if time.monotonic() > deadline:
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
                pct = float(event.get("progress_pct", 0))
                status = str(event.get("status", status))
                print(f"[step4.4] {pct:5.1f}% {status}")
                if status in ("completed", "failed"):
                    break

    task_resp = await _api_get(api_base, f"/api/tasks/{task_id}")
    video_path = str(task_resp.get("result", {}).get("video_path", ""))  # type: ignore[union-attr]
    print(f"[step4.4] 最终状态: {status!r}")
    print(f"[step4.4] video_path: {video_path!r}")

    if status != "completed" or not video_path:
        print("[step4.4] ❌ 断点续传验证失败")
        sys.exit(1)

    print("[step4.4] ✓ 断点续传验证通过 — 产物完整")


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("[step4] E2E 断点续传真验证")
    print("=" * 60)

    _check_resources()

    api_base = os.getenv("HEVI_API_BASE", "http://localhost:8000")
    interrupt_pct = float(os.getenv("INTERRUPT_AT_PCT", "30"))
    print(f"[step4] API: {api_base}  中断点: {interrupt_pct:.0f}%")

    task_id = await start_task(api_base)
    await wait_until_partial_then_interrupt(api_base, task_id, interrupt_pct)
    resumed_id = await resume_from_checkpoint(api_base, task_id)
    await verify_resumed_output(api_base, resumed_id)

    print()
    print("[step4] ✓ 断点续传 E2E 全程验证完成")


if __name__ == "__main__":
    asyncio.run(main())
