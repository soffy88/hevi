#!/usr/bin/env python3
"""step2_full_pipeline.py — E2E 全链路真跑 (1-5min 视频完整管线).

通过 REST API 触发全链路,轮询 SSE 进度,验证最终产物。
需要 hevi API 服务已启动: uv run uvicorn hevi.api.main:app
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── 资源检查 ─────────────────────────────────────────────────────────────────

def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        print(f"[E2E] ❌ 缺少资源: {key}")
        sys.exit(1)
    return val

FAL_API_KEY = _require("FAL_API_KEY")
HEVI_API_BASE = os.getenv("HEVI_API_BASE", "http://localhost:8001")

# ── Auth Helper ─────────────────────────────────────────────────────────────

async def get_auth_token() -> str:
    """Register and login a test user, ensuring credits are enough."""
    email = f"e2e_test_{time.time_ns()}@example.com"
    password = "password123"
    
    async with httpx.AsyncClient(base_url=HEVI_API_BASE, timeout=30.0) as client:
        print(f"[Auth] 注册用户: {email}")
        resp = await client.post("/api/auth/register", json={
            "email": email, "password": password, "display_name": "E2E User"
        })
        resp.raise_for_status()
        
        print("[Auth] 登录获取 Token...")
        resp = await client.post("/api/auth/login", json={
            "email": email, "password": password
        })
        resp.raise_for_status()
        token = resp.json()["access_token"]
        
        # Topup credits (SaaS-2)
        print("[Auth] 手动充值 2000 积分...")
        resp = await client.post("/api/credits/topup", json={"amount": 2000}, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        
        return token

# ── Step 2.1: REST API 触发 ───────────────────────────────────────────────────

async def trigger_pipeline(token: str) -> str:
    payload = {
        "topic": "宇宙中的奇异黑洞之旅",
        "duration_archetype": "1-5min",
        "video_provider": "ltx2_cloud",
        "audio_provider": "ltx2_native",
        "style": "cinematic sci-fi",
        "language": "zh",
    }
    
    print(f"[step2.1] POST /api/tasks/longvideo")
    async with httpx.AsyncClient(base_url=HEVI_API_BASE, timeout=30.0) as client:
        resp = await client.post(
            "/api/tasks/longvideo", 
            json=payload, 
            headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code != 201:
            print(f"[step2.1] ❌ 失败: {resp.text}")
            resp.raise_for_status()
        data = resp.json()
        
    task_id = data["id"]
    print(f"[step2.1] ✓ task_id={task_id!r} status={data['status']!r}")
    return task_id

# ── Step 2.2: SSE 进度 ───────────────────────────────────────────────────────

async def poll_sse_progress(token: str, task_id: str, timeout_s: float = 1200.0) -> str:
    url = f"{HEVI_API_BASE}/api/tasks/{task_id}/progress"
    print(f"[step2.2] SSE 轮询: {url}")
    deadline = time.monotonic() + timeout_s
    status = "unknown"

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as resp:
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

async def verify_output(token: str, task_id: str) -> None:
    async with httpx.AsyncClient(base_url=HEVI_API_BASE, timeout=30.0) as client:
        resp = await client.get(f"/api/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        task = resp.json()

    # In SaaS-3, task structure might have changed slightly or remain the same
    # Checking for result fields
    # Note: actual task structure depends on repository.get_task
    
    print(f"[step2.3] Task Details: {json.dumps(task, indent=2, ensure_ascii=False)}")
    
    result_video = task.get("result_video_path")
    if not result_video:
        print("[step2.3] ❌ result_video_path 缺失")
        sys.exit(1)
        
    print(f"[step2.3] ✓ 产物路径: {result_video}")
    
    # ffprobe verify (if it's a URL, we might need to download it)
    if result_video.startswith("http"):
        print("[step2.3] 下载产物进行 ffprobe 验证...")
        async with httpx.AsyncClient() as client:
            resp = await client.get(result_video)
            video_data = resp.content
            temp_path = Path("output/e2e_step2_final.mp4")
            temp_path.write_bytes(video_data)
    else:
        temp_path = Path(result_video)
        
    if temp_path.exists():
        import subprocess
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0", 
            "-show_entries", "stream=width,height,duration", 
            "-of", "csv=p=0", str(temp_path)
        ], capture_output=True, text=True)
        print(f"[step2.3] ffprobe 结果: {probe.stdout.strip()}")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("[step2] P10.F2 全链路真跑 — 1-5min 视频管线")
    print("=" * 60)
    
    try:
        token = await get_auth_token()
        task_id = await trigger_pipeline(token)
        final_status = await poll_sse_progress(token, task_id)
        
        if final_status == "completed":
            await verify_output(token, task_id)
            print("\n" + "=" * 60)
            print("[step2] ✓ 全链路真跑成功!")
            print("=" * 60)
        else:
            print(f"\n[step2] ❌ 任务未完成: {final_status}")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n[step2] ❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
