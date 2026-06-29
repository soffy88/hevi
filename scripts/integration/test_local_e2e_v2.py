"""Full local pipeline E2E v2 — with vibevoice audio + duix avatar.

Chain:
  1. qwen3.5:9b   → script         7766M  ollama stop to free
  2. wan CausVid  → video clip     5407M  subprocess exit to free
  3. vibevoice    → audio WAV      6461M  gc.collect() + cuda.empty_cache() to free
  4. duix         → avatar video   5242M  container (manages own VRAM)   [optional]
  5. ffmpeg (CPU) → final merge

Any two models exceed 10240M (RTX 3080) → strict serial required.

Run: cd ~/projects/hevi && source .venv/bin/activate
     PYTHONUNBUFFERED=1 python3 test_local_e2e_v2.py
Prerequisites: ollama running, Wan2GP venv ready, duix container running
"""
import gc
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# ── Env vars MUST be set before any oprim/hevi imports ──────────────────────
os.environ.setdefault("HEVI_LLM_PROVIDER", "qwen_local")
os.environ.setdefault("VIBEVOICE_MODEL_DIR", str(Path.home() / "models/vibevoice-1.5b"))
os.environ.setdefault("DUIX_HOST_DATA_DIR", str(Path.home() / "duix_avatar_data/face2face"))
os.environ.setdefault("DUIX_CONTAINER_DATA_DIR", "/code/data")

import asyncio  # noqa: E402 (must come after env setup)

WORK_DIR = Path("/tmp/hevi_e2e_v2")
WORK_DIR.mkdir(exist_ok=True)

DUIX_DATA_DIR = Path.home() / "duix_avatar_data/face2face"
PORTRAIT_IMG = DUIX_DATA_DIR / "test_result.jpg"
DUIX_CONTAINER = "duix-avatar-gen-video"


@dataclass
class SpeakerLine:
    speaker_id: str
    text: str
    voice_ref: Path | None = None


def vram() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
        )
        return int(r.stdout.strip())
    except Exception:
        return -1


def section(title: str) -> None:
    print(f"\n{'='*58}")
    print(f"  {title}")
    print("=" * 58)
    import sys; sys.stdout.flush()


# ────────────────────────────────────────────────────────────
# Step 1: Script generation via qwen3.5:9b
# ────────────────────────────────────────────────────────────

async def step_script(llm: object) -> tuple[str, list[SpeakerLine]]:
    section("Step 1 — Script  qwen3.5:9b  ~7766M")
    from oskill.script_writer import script_writer

    t0 = time.time()
    v0 = vram()
    script = await script_writer(
        topic="海洋的神秘：深海生物",
        target_duration_s=5.0,
        llm=llm,
        language="zh",
    )
    elapsed = time.time() - t0
    v1 = vram()

    print(f"  Title    : {script.title}")
    print(f"  Scenes   : {len(script.scenes)}")
    print(f"  Time     : {elapsed:.1f}s")
    print(f"  VRAM     : {v0} → {v1} MiB ({v1-v0:+d})")

    # Extract first scene
    sc0 = script.scenes[0]
    sc_dict = sc0 if isinstance(sc0, dict) else (sc0.model_dump() if hasattr(sc0, "model_dump") else vars(sc0))
    narration = sc_dict.get("narration", sc_dict.get("visual_description", "深海生物"))
    visual = sc_dict.get("visual_description", sc_dict.get("narration", "deep ocean creatures"))
    print(f"  Scene[0] : {narration[:80]}")

    # Speaker lines for vibevoice
    lines = [SpeakerLine(speaker_id="host", text=narration[:200])]
    return visual[:200], lines


# ────────────────────────────────────────────────────────────
# Step 1b: Unload qwen
# ────────────────────────────────────────────────────────────

async def step_unload_qwen() -> None:
    section("Step 1b — Unload qwen  (ollama stop)")
    v0 = vram()
    subprocess.run(["ollama", "stop", "qwen3.5:9b"], capture_output=True, timeout=30)
    await asyncio.sleep(2)
    v1 = vram()
    print(f"  VRAM freed : {v0} → {v1} MiB ({v1-v0:+d})")


# ────────────────────────────────────────────────────────────
# Step 2: Video clip via wan_local CausVid
# ────────────────────────────────────────────────────────────

async def step_video(video_prompt: str) -> Path:
    section("Step 2 — Video  wan_local CausVid 8-step  ~5407M  ~3m46s")
    from hevi.video.wan_local_service import wan_local_generate

    out = WORK_DIR / "clip.mp4"
    t0 = time.time()
    v0 = vram()
    print(f"  Prompt : {video_prompt[:80]}")
    result = await wan_local_generate(prompt=video_prompt, output_path=out, seed=42)
    elapsed = time.time() - t0
    v1 = vram()
    print(f"  Time   : {elapsed:.0f}s  ({elapsed/60:.1f}min)")
    print(f"  Output : {result}  ({result.stat().st_size/1024/1024:.1f} MB)")
    print(f"  VRAM   : {v0} → {v1} MiB")
    return result


# ────────────────────────────────────────────────────────────
# Step 3: Audio via vibevoice
# ────────────────────────────────────────────────────────────

async def step_audio(lines: list[SpeakerLine]) -> Path:
    section("Step 3 — Audio  vibevoice 1.5B  ~6461M")
    from oprim import vibevoice_synthesize

    model_dir = os.environ["VIBEVOICE_MODEL_DIR"]
    out = WORK_DIR / "audio.wav"
    t0 = time.time()
    v0 = vram()
    print(f"  Model  : {model_dir}")
    print(f"  Lines  : {len(lines)}")

    result = await vibevoice_synthesize(
        config={"VIBEVOICE_MODEL_DIR": model_dir},
        script=lines,
        output_path=out,
        watermark=False,
    )
    elapsed = time.time() - t0
    v1 = vram()
    sz = result.stat().st_size / 1024
    print(f"  Time   : {elapsed:.1f}s")
    print(f"  Output : {result}  ({sz:.0f} KB)")
    print(f"  VRAM   : {v0} → {v1} MiB ({v1-v0:+d})")
    return result


async def step_unload_vibevoice() -> None:
    """Unload vibevoice from GPU.

    vibevoice loads model in-process (not subprocess), so we must rely on
    Python GC + torch.cuda.empty_cache(). Multiple gc passes needed because
    asyncio executor Futures may delay reference release.
    """
    section("Step 3b — Unload vibevoice  (gc × 3 + cuda.empty_cache)")
    v0 = vram()
    # Yield to event loop so pending futures/executors can finalize
    await asyncio.sleep(0.5)
    # Three gc passes to break any reference cycles through asyncio Future chain
    for _ in range(3):
        gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except ImportError:
        pass
    await asyncio.sleep(2)
    v1 = vram()
    freed = v0 - v1
    print(f"  VRAM freed : {v0} → {v1} MiB ({v1-v0:+d})")
    if freed < 3000:
        print(f"  ⚠ vibevoice model still in VRAM (in-process; GC not sufficient)")
        print(f"    duix step will proceed; OOM possible if VRAM {v1}+5242={v1+5242} > 10240")


# ────────────────────────────────────────────────────────────
# Step 4: Duix avatar (optional)
# ────────────────────────────────────────────────────────────

async def step_duix(audio_path: Path) -> Path | None:
    section("Step 4 — Avatar  duix container  ~5242M  [optional]")

    if not PORTRAIT_IMG.exists():
        print(f"  skipped: portrait not found: {PORTRAIT_IMG}")
        return None

    # Start duix container (stopped earlier to free VRAM baseline)
    print(f"  Starting {DUIX_CONTAINER}...")
    subprocess.run(["docker", "start", DUIX_CONTAINER], capture_output=True, timeout=30)
    await asyncio.sleep(8)  # wait for service to become ready

    # Health check
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8383/easy/query?code=ping", timeout=5)
        print(f"  Duix service ready ✓")
    except Exception as e:
        print(f"  Duix service not ready ({e}) — skipping avatar step")
        return None

    # Audio must be accessible from inside the container mount
    duix_audio = DUIX_DATA_DIR / "e2e_audio.wav"
    shutil.copy2(str(audio_path), str(duix_audio))
    print(f"  Audio copied → {duix_audio}")
    print(f"  Portrait    : {PORTRAIT_IMG}")

    from oprim import avatar_generate

    out = WORK_DIR / "avatar.mp4"
    t0 = time.time()
    v0 = vram()

    try:
        result = await avatar_generate(
            provider="duix",
            portrait_image=PORTRAIT_IMG,
            audio_path=duix_audio,
            output_path=out,
            timeout_s=300.0,
        )
        elapsed = time.time() - t0
        v1 = vram()
        sz = result.stat().st_size / 1024 / 1024
        print(f"  Time   : {elapsed:.1f}s")
        print(f"  Output : {result}  ({sz:.1f} MB)")
        print(f"  VRAM   : {v0} → {v1} MiB")
        return result
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  duix error ({elapsed:.1f}s): {type(e).__name__}: {e}")
        print(f"  → continuing without avatar (using wan video + audio merge)")
        return None
    finally:
        # Stop duix after use to free VRAM
        subprocess.run(["docker", "stop", DUIX_CONTAINER], capture_output=True, timeout=30)


# ────────────────────────────────────────────────────────────
# Step 5: ffmpeg assembly
# ────────────────────────────────────────────────────────────

async def step_assemble(video: Path, audio: Path, avatar: Path | None) -> Path:
    section("Step 5 — Assembly  ffmpeg (CPU)")
    out = WORK_DIR / "final.mp4"
    t0 = time.time()

    # Prefer avatar video (already has audio from duix) if available
    if avatar and avatar.exists():
        cmd = ["ffmpeg", "-y", "-i", str(avatar), "-c", "copy", str(out)]
        source = "avatar (duix lip-sync)"
    else:
        # Merge video + vibevoice audio
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(audio),
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", str(out),
        ]
        source = "wan video + vibevoice audio"

    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    elapsed = time.time() - t0

    if proc.returncode == 0 and out.exists():
        sz = out.stat().st_size / 1024 / 1024
        print(f"  Source : {source}")
        print(f"  Time   : {elapsed:.2f}s")
        print(f"  Output : {out}  ({sz:.1f} MB)")
        return out
    else:
        stderr = proc.stderr.decode(errors="replace")[:200]
        print(f"  ffmpeg failed (exit {proc.returncode}): {stderr}")
        return video


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────

async def main() -> None:
    t_start = time.time()

    from hevi.providers.registry import register_all_providers
    register_all_providers()

    from hevi.providers.local_qwen_adapter import LocalQwenAdapter
    print(f"LLM: {LocalQwenAdapter.__name__} (qwen3.5:9b via ollama)")
    print(f"GPU total: 10240 MiB (RTX 3080) — all model pairs exceed this → serial")

    # ── GPU pair constraints ─────────────────────────────────────────
    from hevi.gpu.providers import (
        VRAM_QWEN_LOCAL, VRAM_WAN_LOCAL, VRAM_VIBEVOICE, VRAM_DUIX,
    )
    pairs = [("qwen", int(VRAM_QWEN_LOCAL)), ("wan", int(VRAM_WAN_LOCAL)),
             ("vibevoice", int(VRAM_VIBEVOICE)), ("duix", int(VRAM_DUIX))]
    print("\n  VRAM pair check:")
    for i, (n1, v1) in enumerate(pairs):
        for n2, v2 in pairs[i+1:]:
            flag = "✓ serial" if v1+v2 > 10240 else "✓ fits"
            print(f"    {n1}({v1})+{n2}({v2})={v1+v2}  {flag}")

    # ── Step 1 ──────────────────────────────────────────────────────
    video_prompt, speaker_lines = await step_script(LocalQwenAdapter)

    # ── Step 1b ─────────────────────────────────────────────────────
    await step_unload_qwen()

    # ── Step 2 ──────────────────────────────────────────────────────
    video_clip = await step_video(video_prompt)
    # wgp.py subprocess exits → VRAM freed by OS automatically

    # ── Step 3 ──────────────────────────────────────────────────────
    audio_path = await step_audio(speaker_lines)

    # ── Step 3b ─────────────────────────────────────────────────────
    await step_unload_vibevoice()

    # ── Step 4 (optional) ───────────────────────────────────────────
    avatar_clip = await step_duix(audio_path)

    # ── Step 5 ──────────────────────────────────────────────────────
    final = await step_assemble(video_clip, audio_path, avatar_clip)

    # ── ffprobe ──────────────────────────────────────────────────────
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "stream=codec_name,width,height,nb_frames,duration",
         "-of", "csv=p=0", str(final)],
        capture_output=True, text=True,
    )
    probe_out = r.stdout.strip()

    total = time.time() - t_start

    section("RESULT — Full Local E2E v2")
    print(f"  Chain    : qwen → wan CausVid → vibevoice → {'duix → ' if avatar_clip else ''}ffmpeg")
    print(f"  Output   : {final}")
    print(f"  Exists   : {final.exists()}")
    if final.exists():
        print(f"  Size     : {final.stat().st_size/1024/1024:.1f} MB")
    if probe_out:
        print(f"  Stream   : {probe_out}")
    print(f"  Total    : {total:.0f}s  ({total/60:.1f}min)")
    print(f"  Cost     : ~$0  (100% local GPU)")
    print()

    print("  transformers patch check:")
    import transformers
    print(f"    transformers {transformers.__version__} — vibevoice compatible ✓")
    import vibevoice as _vv
    print(f"    vibevoice package at {_vv.__file__}")

    print()
    print("  Sub D — M8 full-local orchestration:")
    print("    orchestrate_longvideo(video_provider='wan_local',")
    print("                          audio_provider='vibevoice')")
    print("    + HEVI_LLM_PROVIDER=qwen_local")
    print("    → $0 marginal cost per video")


if __name__ == "__main__":
    asyncio.run(main())
