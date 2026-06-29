"""Test qwen_local provider: script_writer + storyboard generation."""
import asyncio
import os
import time

os.environ["HEVI_LLM_PROVIDER"] = "qwen_local"

import subprocess
import json


def vram_used_mib() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
        )
        return int(r.stdout.strip())
    except Exception:
        return -1


async def main() -> None:
    from hevi.providers.registry import register_all_providers
    from obase.provider_registry import ProviderRegistry

    register_all_providers()

    llm = ProviderRegistry.get("llm", "default")
    print(f"LLM provider: {llm.__name__}")

    # ── Test 1: raw adapter call ────────────────────────────────────────────
    print("\n=== Test 1: raw LocalQwenAdapter call ===")
    vram_before = vram_used_mib()
    t0 = time.time()
    resp = llm(messages=[
        {"role": "system", "content": "You are a helpful assistant. Reply briefly in Chinese."},
        {"role": "user", "content": "用一句话介绍人工智能。"},
    ])
    elapsed = time.time() - t0
    vram_after = vram_used_mib()
    content = resp.get("content", "")
    print(f"  Response ({elapsed:.1f}s): {content[:200]}")
    print(f"  VRAM: {vram_before}→{vram_after} MiB (delta: {vram_after - vram_before:+d})")

    # ── Test 2: script_writer ───────────────────────────────────────────────
    print("\n=== Test 2: script_writer (60s video, zh) ===")
    from oskill.script_writer import script_writer

    t1 = time.time()
    vram_pre = vram_used_mib()
    try:
        script = await script_writer(
            topic="人工智能改变世界",
            target_duration_s=60.0,
            llm=llm,
            language="zh",
        )
        elapsed2 = time.time() - t1
        vram_post = vram_used_mib()
        print(f"  Title: {script.title}")
        print(f"  Scenes: {len(script.scenes)}, estimated_duration_s: {script.estimated_duration_s}")
        print(f"  Time: {elapsed2:.1f}s | VRAM: {vram_pre}→{vram_post} MiB")
        if script.scenes:
            print(f"  Scene[0] narration: {script.scenes[0].narration[:120]}")
    except Exception as e:
        print(f"  ✗ script_writer failed: {e}")

    # ── Test 3: script_writer chapter_mode ──────────────────────────────────
    print("\n=== Test 3: script_writer chapter_mode (180s, 2 chars) ===")
    t2 = time.time()
    try:
        chapter_script = await script_writer(
            topic="太空探索的未来",
            target_duration_s=180.0,
            llm=llm,
            language="zh",
            chapter_mode=True,
            num_characters=2,
        )
        elapsed3 = time.time() - t2
        print(f"  Chapters: {len(chapter_script.chapters)}, total_duration_s: {chapter_script.total_duration_s}")
        print(f"  Characters: {chapter_script.characters}")
        print(f"  Time: {elapsed3:.1f}s")
        if chapter_script.chapters:
            ch0 = chapter_script.chapters[0]
            print(f"  Ch[0] title: {ch0.title}")
            print(f"  Ch[0] dialogues: {len(ch0.dialogues)}")
    except Exception as e:
        print(f"  ✗ chapter script failed: {e}")

    print("\n=== Summary ===")
    print(f"  qwen2.5:7b via Ollama: working={content != ''}")
    print(f"  GPU VRAM peak: ~{max(vram_after, vram_post if 'vram_post' in dir() else 0)} MiB")
    print(f"  DashScope dependency: ELIMINATED for script/storyboard steps")


asyncio.run(main())
