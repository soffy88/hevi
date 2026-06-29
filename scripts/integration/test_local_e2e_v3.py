"""Full local pipeline E2E v3 — vibevoice subprocess isolation + duix no-OOM.

Chain:
  1. qwen3.5:9b   → script         7766M  ollama stop → full VRAM freed
  2. wan CausVid  → video clip     5407M  subprocess exit → full VRAM freed
  3. vibevoice    → audio WAV      8513M  subprocess exit → full VRAM freed  ← key fix
  4. duix         → avatar video   5242M  container start → 10240M available ✓
  5. ffmpeg (CPU) → final merge

v2 vs v3:
  v2: vibevoice in-process (gc only freed 78 MiB) → duix OOM (8437+5242>10240)
  v3: vibevoice subprocess (OS reclaims on exit)   → duix OK (<2600+5242<10240)

Run: cd ~/projects/hevi && source .venv/bin/activate
     PYTHONUNBUFFERED=1 python3 test_local_e2e_v3.py
Prerequisites: ollama running, Wan2GP venv ready, duix container created
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Env vars MUST be set before any oprim/hevi imports
os.environ.setdefault("HEVI_LLM_PROVIDER", "qwen_local")
os.environ.setdefault("VIBEVOICE_MODEL_DIR", str(Path.home() / "models/vibevoice-1.5b"))
os.environ.setdefault("DUIX_HOST_DATA_DIR", str(Path.home() / "duix_avatar_data/face2face"))
os.environ.setdefault("DUIX_CONTAINER_DATA_DIR", "/code/data")

import asyncio  # noqa: E402

WORK_DIR = Path("/tmp/hevi_e2e_v3")
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
    sys.stdout.flush()


# ────────────────────────────────────────────────────────────
# Step 1: Script generation via qwen3.5:9b
# ────────────────────────────────────────────────────────────

async def step_script(llm: object) -> tuple[str, list[SpeakerLine]]:
    section("Step 1 — Script  qwen3.5:9b  ~7766M")
    from oskill.script_writer import script_writer

    t0 = time.time()
    v0 = vram()
    script = await script_writer(
        topic="人工智能改变世界",
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

    sc0 = script.scenes[0]
    sc_dict = sc0 if isinstance(sc0, dict) else (
        sc0.model_dump() if hasattr(sc0, "model_dump") else vars(sc0)
    )
    narration = sc_dict.get("narration", sc_dict.get("visual_description", "人工智能"))
    visual = sc_dict.get("visual_description", sc_dict.get("narration", "AI technology"))
    print(f"  Scene[0] : {narration[:80]}")

    lines = [SpeakerLine(speaker_id="host", text=narration[:200])]
    return visual[:200], lines


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
    print(f"  VRAM   : {v0} → {v1} MiB  (subprocess exit → OS reclaim ✓)")
    return result


# ────────────────────────────────────────────────────────────
# Step 3: Audio via vibevoice subprocess
# ────────────────────────────────────────────────────────────

async def step_audio(lines: list[SpeakerLine]) -> Path:
    section("Step 3 — Audio  vibevoice 1.5B subprocess  ~8513M")
    from hevi.audio.tts_service import synthesize_dialogue

    model_dir = os.environ["VIBEVOICE_MODEL_DIR"]
    out = WORK_DIR / "audio.wav"
    t0 = time.time()
    v0 = vram()
    print(f"  Model  : {model_dir}")
    print(f"  Lines  : {len(lines)}")

    result = await synthesize_dialogue(
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
    print(f"  VRAM   : {v0} → {v1} MiB  (subprocess exit → OS reclaim)")
    freed = v0 - v1
    if freed < 3000:
        print(f"  ⚠ VRAM freed only {freed} MiB — subprocess may still be exiting")
    else:
        print(f"  ✓ VRAM fully reclaimed ({freed:+d} MiB freed)")
    return result


# ────────────────────────────────────────────────────────────
# Step 4: Duix avatar
# ────────────────────────────────────────────────────────────

async def step_duix(audio_path: Path) -> Path | None:
    section("Step 4 — Avatar  duix container  ~5242M")

    if not PORTRAIT_IMG.exists():
        print(f"  skipped: portrait not found: {PORTRAIT_IMG}")
        return None

    v_before = vram()
    print(f"  VRAM before duix start : {v_before} MiB  (need headroom ≥5242)")
    if v_before + 5242 > 10240:
        print(f"  ⚠ VRAM {v_before}+5242={v_before+5242} > 10240 — OOM risk!")
    else:
        print(f"  ✓ Sufficient VRAM: {v_before}+5242={v_before+5242} ≤ 10240")

    print(f"  Starting {DUIX_CONTAINER}...")
    subprocess.run(["docker", "start", DUIX_CONTAINER], capture_output=True, timeout=30)
    await asyncio.sleep(10)  # wait for service ready

    # Health check
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8383/easy/query?code=ping", timeout=8)
        print("  Duix service ready ✓")
    except Exception as e:
        print(f"  Duix service not ready ({e}) — skipping avatar step")
        subprocess.run(["docker", "stop", DUIX_CONTAINER], capture_output=True, timeout=30)
        return None

    duix_audio = DUIX_DATA_DIR / "e2e_v3_audio.wav"
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
        print("  → fallback: wan video + vibevoice audio merge")
        return None
    finally:
        subprocess.run(["docker", "stop", DUIX_CONTAINER], capture_output=True, timeout=30)


# ────────────────────────────────────────────────────────────
# Step 5: ffmpeg assembly
# ────────────────────────────────────────────────────────────

async def step_assemble(video: Path, audio: Path, avatar: Path | None) -> Path:
    section("Step 5 — Assembly  ffmpeg (CPU)")
    out = WORK_DIR / "final.mp4"
    t0 = time.time()

    if avatar and avatar.exists():
        cmd = ["ffmpeg", "-y", "-i", str(avatar), "-c", "copy", str(out)]
        source = "duix avatar (lip-sync)"
    else:
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
    print("GPU total: 10240 MiB (RTX 3080)")
    print("vibevoice: subprocess isolation (OS VRAM reclaim on exit) ← v3 key fix")

    from hevi.gpu.providers import (
        VRAM_DUIX, VRAM_QWEN_LOCAL, VRAM_VIBEVOICE, VRAM_WAN_LOCAL,
    )
    pairs = [
        ("qwen", int(VRAM_QWEN_LOCAL)),
        ("wan", int(VRAM_WAN_LOCAL)),
        ("vibevoice", int(VRAM_VIBEVOICE)),
        ("duix", int(VRAM_DUIX)),
    ]
    print("\n  VRAM pair check (serial required if sum > 10240):")
    for i, (n1, v1) in enumerate(pairs):
        for n2, v2 in pairs[i + 1:]:
            flag = "serial" if v1 + v2 > 10240 else "fits"
            print(f"    {n1}({v1})+{n2}({v2})={v1+v2}  ✓ {flag}")

    # Stop any running ollama models (may have stale generation from previous run)
    subprocess.run(["ollama", "stop", "qwen3.5:9b"], capture_output=True, timeout=30)
    # Stop duix before starting to free its VRAM for baseline
    subprocess.run(["docker", "stop", DUIX_CONTAINER], capture_output=True, timeout=30)
    await asyncio.sleep(2)
    print(f"\n  Baseline VRAM (after ollama stop + docker stop duix): {vram()} MiB")

    video_prompt, speaker_lines = await step_script(LocalQwenAdapter)
    await step_unload_qwen()
    video_clip = await step_video(video_prompt)
    audio_path = await step_audio(speaker_lines)
    # vibevoice subprocess exits → OS fully reclaims VRAM → duix can start
    await asyncio.sleep(1)
    avatar_clip = await step_duix(audio_path)
    final = await step_assemble(video_clip, audio_path, avatar_clip)

    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "stream=codec_name,width,height,duration",
         "-of", "csv=p=0", str(final)],
        capture_output=True, text=True,
    )
    probe_out = r.stdout.strip()

    total = time.time() - t_start

    section("RESULT — Full Local E2E v3")
    print(f"  Chain    : qwen → wan → vibevoice(subprocess) → {'duix → ' if avatar_clip else ''}ffmpeg")
    print(f"  Output   : {final}")
    print(f"  Exists   : {final.exists()}")
    if final.exists():
        print(f"  Size     : {final.stat().st_size/1024/1024:.1f} MB")
    if probe_out:
        print(f"  Stream   : {probe_out}")
    print(f"  Total    : {total:.0f}s  ({total/60:.1f}min)")
    print(f"  Cost     : ~$0  (100% local GPU)")

    print()
    print("  vibevoice subprocess isolation:")
    print("    v2: gc only freed 78 MiB (model residue 8437 MiB)")
    print("    v3: subprocess exit → OS reclaims full VRAM ✓")

    print()
    print("  Sub D — M8 full-local orchestration:")
    print("    orchestrate_longvideo(video_provider='wan_local',")
    print("                          audio_provider='vibevoice')")
    print("    + HEVI_LLM_PROVIDER=qwen_local")
    print("    → $0 marginal cost, duix avatar capable")


if __name__ == "__main__":
    asyncio.run(main())
