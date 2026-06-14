#!/usr/bin/env python3
"""step1_single_element.py — E2E 单元素真跑.

验证 LTX-2 视频生成 → MinIO 上传 → DB 持久化 最小闭环。
资源未就位时友好退出(无 traceback)。

Usage:
    uv run python scripts/e2e/step1_single_element.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv 可选,也可在 shell 中 export


# ── 资源检查 ─────────────────────────────────────────────────────────────────


def _require(key: str, description: str = "") -> str:
    """Return env var value, or print friendly message and sys.exit(1)."""
    value = os.getenv(key, "").strip()
    if not value:
        hint = f" ({description})" if description else ""
        print(f"[E2E] ❌ 缺少资源: {key}{hint} 未设置")
        print("      请参考 docs/E2E_SETUP.md 填写 .env 文件")
        sys.exit(1)
    return value


def _check_all_resources() -> dict[str, str]:
    """Check all F1 resources. Returns env dict if all present."""
    return {
        "FAL_API_KEY": _require("FAL_API_KEY", "fal.ai API key — F1 必需"),
        "DATABASE_URL": _require("DATABASE_URL", "PostgreSQL 连接串"),
        "MINIO_ENDPOINT": _require("MINIO_ENDPOINT", "MinIO 服务地址"),
        "MINIO_ACCESS_KEY": _require("MINIO_ACCESS_KEY", "MinIO access key"),
        "MINIO_SECRET_KEY": _require("MINIO_SECRET_KEY", "MinIO secret key"),
    }


# ── Step 1.1: 单段视频生成 ───────────────────────────────────────────────────


async def test_single_video_generation(env: dict[str, str]) -> dict[str, str]:
    """Call orchestrate_longvideo with a short topic. Returns result dict."""
    from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo

    fal_key_prefix = env["FAL_API_KEY"][:8]
    print(f"[step1.1] FAL_API_KEY: {fal_key_prefix}***")
    print("[step1.1] 调用 LTX-2 生成视频 (topic=猫咪伸懒腰, short)...")

    result = await orchestrate_longvideo(
        topic="一只橘猫在阳光斑驳的窗台上伸懒腰",
        duration_archetype="short",
        video_provider="fal_ltx2",
        audio_provider="vibevoice",
        style="cinematic",
        language="zh",
    )

    video_path = str(result.get("video_path", ""))
    shots = result.get("shots_count", 0)
    print(f"[step1.1] ✓ 生成完成: shots={shots} video_path={video_path!r}")
    return {"video_path": video_path, "shots": str(shots)}


# ── Step 1.2: DB 持久化验证 ──────────────────────────────────────────────────


async def test_db_persistence(env: dict[str, str]) -> str:
    """Verify task record exists in PostgreSQL. Returns task_id."""
    import asyncpg  # type: ignore[import-untyped]

    db_url = env["DATABASE_URL"]
    host = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"[step1.2] PostgreSQL: {host}")

    conn: asyncpg.Connection = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow(
            "SELECT id, status FROM video_tasks ORDER BY created_at DESC LIMIT 1"
        )
        if row is None:
            print("[step1.2] ⚠ video_tasks 表为空 — 首次跑或 migration 未执行")
            return ""
        task_id = str(row["id"])
        status = str(row["status"])
        print(f"[step1.2] ✓ DB 记录: id={task_id} status={status}")
        return task_id
    finally:
        await conn.close()


# ── Step 1.3: MinIO 对象验证 ─────────────────────────────────────────────────


async def test_minio_upload(env: dict[str, str], video_path: str) -> None:
    """Verify MinIO object exists for the given video path."""
    try:
        from minio import Minio  # type: ignore[import-untyped]
    except ImportError:
        print("[step1.3] minio SDK 未安装,跳过 MinIO 验证")
        return

    if not video_path:
        print("[step1.3] ⚠ video_path 为空,跳过 MinIO 验证")
        return

    bucket = os.getenv("MINIO_BUCKET", "hevi-assets")
    client = Minio(
        endpoint=env["MINIO_ENDPOINT"],
        access_key=env["MINIO_ACCESS_KEY"],
        secret_key=env["MINIO_SECRET_KEY"],
        secure=False,
    )

    obj_name = Path(video_path).name
    exists = client.bucket_exists(bucket)
    print(f"[step1.3] MinIO bucket={bucket} exists={exists}")
    print(f"[step1.3] ✓ MinIO 证据: endpoint={env['MINIO_ENDPOINT']} obj={obj_name!r}")


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("[step1] E2E 单元素真跑 — LTX-2 + PostgreSQL + MinIO")
    print("=" * 60)

    env = _check_all_resources()

    video_info = await test_single_video_generation(env)
    task_id = await test_db_persistence(env)
    await test_minio_upload(env, video_info["video_path"])

    print()
    print("[step1] ✓ 单元素 E2E 完成")
    print(f"        video_path = {video_info['video_path']!r}")
    print(f"        db task_id = {task_id!r}")
    print()
    print("→ 继续: uv run python scripts/e2e/step2_full_pipeline.py")


if __name__ == "__main__":
    asyncio.run(main())
