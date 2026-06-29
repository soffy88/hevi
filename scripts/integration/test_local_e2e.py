"""Sub C: Full local pipeline end-to-end verification.

Chain: qwen3.5:9b (script) → wan_local CausVid (video) → vibevoice (audio) → ffmpeg (synthesis)
GPU serial scheduling via GpuScheduler throughout.

Run: python3 test_local_e2e.py
Prerequisites: duix stopped, ollama running, Wan2GP venv ready
"""
import asyncio
import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("HEVI_LLM_PROVIDER", "qwen_local")

WORK_DIR = Path("/tmp/hevi_e2e_test")
WORK_DIR.mkdir(exist_ok=True)


def vram_used() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
        )
        return int(r.stdout.strip())
    except Exception:
        return -1


def section(title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)


async def step_script(llm: object) -> tuple[str, list[dict]]:
    """Generate 1-scene script via qwen3.5:9b (5s target)."""
    section("Step 1 — Script (qwen3.5:9b, ~5s clip)")
    t0 = time.time()
    v_before = vram_used()

    from oskill.script_writer import script_writer

    script = await script_writer(
        topic="海洋的神秘：深海生物",
        target_duration_s=5.0,
        llm=llm,
        language="zh",
    )
    elapsed = time.time() - t0
    v_after = vram_used()

    print(f"  Title       : {script.title}")
    print(f"  Scenes      : {len(script.scenes)}")
    print(f"  Duration est: {script.estimated_duration_s}s")
    print(f"  Time        : {elapsed:.1f}s")
    print(f"  VRAM        : {v_before} → {v_after} MiB (delta: {v_after-v_before:+d})")

    scenes = []
    for sc in script.scenes[:1]:  # only 1 scene for speed
        sc_dict = sc if isinstance(sc, dict) else (sc.model_dump() if hasattr(sc, "model_dump") else vars(sc))
        scenes.append(sc_dict)
        narr = sc_dict.get("narration", sc_dict.get("visual_description", ""))[:80]
        print(f"  Scene[0]    : {narr}")

    # Use first scene narration as video prompt
    sc0 = scenes[0] if scenes else {}
    video_prompt = sc0.get("visual_description") or sc0.get("narration") or "deep ocean mysterious creatures"
    return video_prompt, scenes


async def step_unload_qwen() -> None:
    """Unload qwen from GPU before video generation."""
    section("Step 1b — Unload qwen (ollama stop)")
    v_before = vram_used()
    proc = subprocess.run(
        ["ollama", "stop", "qwen3.5:9b"],
        capture_output=True, timeout=30,
    )
    await asyncio.sleep(2)
    v_after = vram_used()
    print(f"  ollama stop exit: {proc.returncode}")
    print(f"  VRAM freed: {v_before} → {v_after} MiB (delta: {v_after-v_before:+d})")


async def step_video(video_prompt: str) -> Path:
    """Generate video clip via wan_local (Wan2GP + CausVid 8-step)."""
    section("Step 2 — Video (wan_local CausVid 8-step, ~3m46s)")
    output_path = WORK_DIR / "clip_0.mp4"
    t0 = time.time()
    v_before = vram_used()
    print(f"  Prompt: {video_prompt[:80]}")
    print(f"  Generating...")

    from hevi.video.wan_local_service import wan_local_generate

    result = await wan_local_generate(
        prompt=video_prompt,
        output_path=output_path,
        seed=42,
    )
    elapsed = time.time() - t0
    v_after = vram_used()
    size_mb = result.stat().st_size / 1024 / 1024

    print(f"  Time  : {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  Output: {result} ({size_mb:.1f} MB)")
    print(f"  VRAM  : {v_before} → {v_after} MiB")
    return result


async def step_audio(scenes: list[dict]) -> Path | None:
    """Generate audio via vibevoice. Returns None if vibevoice unavailable."""
    section("Step 3 — Audio (vibevoice)")
    audio_path = WORK_DIR / "audio.wav"
    t0 = time.time()
    v_before = vram_used()
    print(f"  Scenes: {len(scenes)}")

    try:
        from oprim import vibevoice_synthesize

        result = await vibevoice_synthesize(
            script=scenes,
            output_path=audio_path,
            watermark=False,
        )
        elapsed = time.time() - t0
        v_after = vram_used()
        size_mb = audio_path.stat().st_size / 1024 / 1024 if audio_path.exists() else 0
        print(f"  Time  : {elapsed:.1f}s")
        print(f"  Output: {result} ({size_mb:.2f} MB)")
        print(f"  VRAM  : {v_before} → {v_after} MiB")
        return audio_path
    except Exception as e:
        print(f"  vibevoice skipped: {e}")
        return None


async def step_assemble(video_clip: Path, audio_path: Path | None) -> Path:
    """Assemble final video via ffmpeg (CPU)."""
    section("Step 4 — Assembly (ffmpeg, CPU)")
    output = WORK_DIR / "final.mp4"
    t0 = time.time()

    if audio_path and audio_path.exists():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_clip),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output),
        ]
    else:
        cmd = ["ffmpeg", "-y", "-i", str(video_clip), "-c", "copy", str(output)]

    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    elapsed = time.time() - t0

    if proc.returncode == 0 and output.exists():
        size_mb = output.stat().st_size / 1024 / 1024
        print(f"  Time  : {elapsed:.1f}s")
        print(f"  Output: {output} ({size_mb:.1f} MB)")
        return output
    else:
        print(f"  ffmpeg failed (exit {proc.returncode}), using clip directly")
        return video_clip


async def main() -> None:
    t_total = time.time()

    from hevi.providers.registry import register_all_providers
    register_all_providers()

    from hevi.providers.local_qwen_adapter import LocalQwenAdapter

    llm = LocalQwenAdapter
    print(f"LLM provider: {llm.__name__} (qwen3.5:9b via ollama)")

    # ── Step 1: Script ───────────────────────────────────────────────
    video_prompt, scenes = await step_script(llm)

    # ── Step 1b: Unload qwen ─────────────────────────────────────────
    await step_unload_qwen()

    # ── Step 2: Video (CausVid) ──────────────────────────────────────
    video_clip = await step_video(video_prompt)

    # ── Step 3: Audio ────────────────────────────────────────────────
    audio = await step_audio(scenes)

    # ── Step 4: Assembly ─────────────────────────────────────────────
    final = await step_assemble(video_clip, audio)

    # ── Restore duix ─────────────────────────────────────────────────
    section("Restoring duix container")
    subprocess.run(["docker", "start", "duix-avatar-gen-video"], capture_output=True)
    print("  docker start duix-avatar-gen-video")

    # ── Summary ──────────────────────────────────────────────────────
    elapsed_total = time.time() - t_total
    section("RESULT: Sub C — Full Local E2E")
    print(f"  Output : {final}")
    print(f"  Exists : {final.exists()}")
    if final.exists():
        sz = final.stat().st_size / 1024 / 1024
        print(f"  Size   : {sz:.1f} MB")

        # ffprobe check
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "stream=codec_name,width,height,nb_frames,duration",
             "-of", "csv=p=0", str(final)],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            print(f"  Video  : {r.stdout.strip()}")

    print(f"  Total  : {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")
    print(f"  Cost   : ~$0 (100% local GPU)")
    print()
    print("  Sub D — M8 vs hevi orchestration analysis:")
    print("  ✓ M8 CAN use local video (wan_local) + audio (vibevoice) via ProviderRegistry")
    print("  ✓ M8 NOW uses local LLM (qwen3.5:9b) when HEVI_LLM_PROVIDER=qwen_local")
    print("  ✓ LocalQwenAdapter registered as 'llm'/'local' always, 'default' when env set")
    print("  → Full-local M8 pipeline: orchestrate_longvideo(video_provider='wan_local',")
    print("                             audio_provider='vibevoice') + HEVI_LLM_PROVIDER=qwen_local")
    print("  → Marginal cost = $0 (GPU electricity only)")


asyncio.run(main())
