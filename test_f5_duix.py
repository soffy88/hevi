"""F5 真跑: Duix 唇形合成验证.

前置: nvidia-container-toolkit 已安装, Duix lite 服务已启动:
  ! sudo apt-get install -y nvidia-container-toolkit && sudo systemctl restart docker
  cd ~/Duix-Avatar/deploy && docker compose -f docker-compose-lite.yml up -d
  docker compose -f docker-compose-lite.yml ps   # 确认 Running

用法: /home/soffy/projects/hevi/.venv/bin/python test_f5_duix.py
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path


DUIX_DATA_DIR = Path.home() / "duix_avatar_data/face2face"
OUTPUT_DIR = Path("output/f5_duix")
PORTRAIT_SRC = Path("output/e2e_step1_processed/cover.jpg")
AUDIO_SRC = Path("output/f4a_tts/single_speaker.wav")

# Duix container mounts ~/duix_avatar_data/face2face → /code/data
# Pass paths as seen from inside container
PORTRAIT_IN_CONTAINER = "/code/data/portrait.jpg"
AUDIO_IN_CONTAINER = "/code/data/audio.wav"


def _mem_mib() -> int:
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def _check_service() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8383/easy/query?code=ping", timeout=5)
        return True
    except Exception:
        return False


async def run_f5() -> None:
    from hevi.audio.avatar_service import generate_avatar_clip

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DUIX_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Stage files into the mounted volume so the container can read them
    portrait_staged = DUIX_DATA_DIR / "portrait.jpg"
    audio_staged = DUIX_DATA_DIR / "audio.wav"
    shutil.copy2(PORTRAIT_SRC, portrait_staged)
    shutil.copy2(AUDIO_SRC, audio_staged)
    print(f"[F5] 文件已复制到容器挂载目录: {DUIX_DATA_DIR}")
    print(f"     portrait: {portrait_staged} ({portrait_staged.stat().st_size} bytes)")
    print(f"     audio:    {audio_staged} ({audio_staged.stat().st_size} bytes)")

    # Check GPU before
    mem_before = _mem_mib()
    print(f"\n[F5] GPU 显存(调用前): {mem_before} MiB")

    # Call through hevi's avatar_service
    out_path = OUTPUT_DIR / "f5_lipsync.mp4"
    print(f"\n[F5] 调用 generate_avatar_clip ...")
    t0 = time.perf_counter()

    try:
        result = await generate_avatar_clip(
            config=None,
            portrait_image=Path(PORTRAIT_IN_CONTAINER),
            audio_path=Path(AUDIO_IN_CONTAINER),
            output_path=out_path,
        )
        elapsed = time.perf_counter() - t0
        mem_after = _mem_mib()

        size = result.stat().st_size if result.exists() else 0
        print(f"[F5] 完成! 耗时: {elapsed:.1f}s | 输出: {result} ({size} bytes)")
        print(f"[F5] GPU 显存(完成后): {mem_after} MiB | 增量: +{mem_after - mem_before} MiB")

        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration,size : stream=codec_name,width,height,r_frame_rate",
             "-of", "default=noprint_wrappers=1", str(result)],
            capture_output=True, text=True,
        )
        print(f"[F5] ffprobe:\n{r.stdout.strip() or r.stderr.strip()}")

    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"[F5] 错误 ({elapsed:.1f}s): {type(exc).__name__}: {exc}")
        raise

    print("\n" + "=" * 60)
    print("[F5] Duix 唇形合成真跑总结")
    print("=" * 60)
    print(f"  Portrait:         {PORTRAIT_SRC} → {PORTRAIT_IN_CONTAINER}")
    print(f"  Audio (F4a):      {AUDIO_SRC} → {AUDIO_IN_CONTAINER}")
    print(f"  输出视频:          {out_path}")
    print(f"  GPU 显存峰值:      {mem_after} MiB")
    print(f"  GPU 增量:          +{mem_after - mem_before} MiB")
    print(f"  耗时:              {elapsed:.1f}s")
    print("=" * 60)


def main() -> None:
    print("[F5] Duix 唇形合成 真跑")
    print(f"     服务地址: http://127.0.0.1:8383")

    # Quick ping to confirm service is up
    print("[F5] 检查 Duix 服务连通性 ...")
    if not _check_service():
        print("[F5] ERROR: Duix 服务未响应 http://127.0.0.1:8383")
        print("     请先启动:")
        print("       cd ~/Duix-Avatar/deploy && docker compose -f docker-compose-lite.yml up -d")
        raise SystemExit(1)
    print("[F5] Duix 服务在线 ✓")

    asyncio.run(run_f5())


if __name__ == "__main__":
    main()
