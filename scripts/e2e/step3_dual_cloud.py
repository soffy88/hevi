#!/usr/bin/env python3
"""step3_dual_cloud.py — E2E 双 Cloud 真跑 (Wan 单独 + LTX2<->Wan Fallback).

验证:
1. Wan 单独真跑 (1-5min 全链路)
2. Fallback LTX2 -> Wan (通过配置错误 HEVI_CHAOS_FAIL_LTX2)
3. Fallback Wan -> LTX2 (通过配置错误 HEVI_CHAOS_FAIL_WAN)
4. provider_health_check (Fallback 过程中自然触发)
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        print(f"[E2E] ❌ 缺少资源: {key}")
        sys.exit(1)
    return val

FAL_API_KEY = _require("FAL_API_KEY")
DASHSCOPE_API_KEY = _require("DASHSCOPE_API_KEY")

PORT = 9008
BASE_URL = f"http://127.0.0.1:{PORT}"

async def wait_for_server():
    for _ in range(30):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{BASE_URL}/api/health")
                if r.status_code == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("Server failed to start")

async def get_auth_token() -> str:
    email = f"e2e_test_{time.time_ns()}@example.com"
    password = "password123"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        r = await client.post("/api/auth/register", json={
            "email": email, "password": password, "display_name": "E2E User"
        })
        r.raise_for_status()
        r = await client.post("/api/auth/login", json={
            "email": email, "password": password
        })
        r.raise_for_status()
        token = r.json()["access_token"]
        r = await client.post("/api/credits/topup", json={"amount": 5000}, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return token

async def run_pipeline(token: str, provider: str, expected_final_provider: str, scenario: str):
    payload = {
        "topic": f"Scenario {scenario}: A red balloon journey",
        "duration_archetype": "1-5min",
        "video_provider": provider,
        "audio_provider": "ltx2_native",
    }
    print(f"    -> 触发任务: {provider}")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        r = await client.post("/api/tasks/longvideo", json=payload, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        task_id = r.json()["id"]

    print(f"    -> 轮询 SSE...")
    url = f"{BASE_URL}/api/tasks/{task_id}/progress"
    deadline = time.monotonic() + 1800
    status = "unknown"
    async with httpx.AsyncClient(timeout=1800.0) as client:
        async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if time.monotonic() > deadline:
                    break
                if not line.startswith("data:"): continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]": break
                try: event = json.loads(raw)
                except: continue
                pct = event.get("progress_pct", 0)
                msg = event.get("message", "")
                status = event.get("status", status)
                print(f"      [{pct:3.0f}%] {status} - {msg}")
                if status in ("completed", "failed"): break

    if status != "completed":
        raise RuntimeError(f"Task failed with status {status}")

    # Fetch task to check actual provider used
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        r = await client.get(f"/api/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        task = r.json()
        used = task["video_provider"]
        print(f"    -> 最终使用的提供商: {used}")
        if used != expected_final_provider:
            raise RuntimeError(f"Expected provider {expected_final_provider}, but got {used}")
        cost = task["config_json"].get("actual_usd")
        print(f"    -> 真实成本: ${cost}")

async def test_scenario(name: str, env_vars: dict, provider: str, expected: str):
    print("=" * 60)
    print(f"[step3] 场景: {name}")
    print("=" * 60)
    
    env = os.environ.copy()
    env.update(env_vars)
    
    log_file = open(f"step3_{name.split()[0]}.log", "w")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "hevi.api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT
    )
    
    try:
        await wait_for_server()
        token = await get_auth_token()
        await run_pipeline(token, provider, expected, name)
        print(f"✓ 场景 '{name}' 验证通过\n")
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait()
        log_file.close()

async def main():
    try:
        # 1. Wan 单独真跑
        await test_scenario(
            name="Wan单独",
            env_vars={"HEVI_API_BASE": BASE_URL},
            provider="wan_cloud",
            expected="wan_cloud"
        )
        
        # 2. Fallback: LTX2 -> Wan (LTX2 失败)
        await test_scenario(
            name="Fallback_LTX2_Wan",
            env_vars={
                "HEVI_CHAOS_FAIL_LTX2": "true",
                "HEVI_API_BASE": BASE_URL
            },
            provider="ltx2_cloud",
            expected="wan_cloud"
        )

        # 3. Fallback: Wan -> LTX2 (Wan 失败)
        await test_scenario(
            name="Fallback_Wan_LTX2",
            env_vars={
                "HEVI_CHAOS_FAIL_WAN": "true",
                "HEVI_API_BASE": BASE_URL
            },
            provider="wan_cloud",
            expected="ltx2_cloud"
        )

        print("🎉 所有 step3 验证通过！")
    except Exception as e:
        print(f"\n❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
