"""Generate real sample videos for Motion FX and reframe."""

import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from hevi.motion_fx.reframe import compute_reframe_windows, reframe
from hevi.motion_fx.transitions import apply_transition, probe_video

SAMPLE_DIR = Path("samples/aimotion_fx")
SAMPLE_DIR.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def make_clip_a(out_path: Path, width: int = 720, height: int = 1280, duration: float = 3.5, fps: int = 25):
    """Generate Scene A: High tech blueprint drafting aesthetic with moving vector lines and labels."""
    total_frames = int(round(duration * fps))
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(total_frames):
        t = i / float(fps)
        img = np.zeros((height, width, 3), dtype=np.uint8)
        # Gradient background
        img[:, :] = [35, 20, 10]  # Deep navy
        # Draw tech grid
        for gy in range(0, height, 60):
            cv2.line(img, (0, gy), (width, gy), (50, 35, 20), 1)
        for gx in range(0, width, 60):
            cv2.line(img, (gx, 0), (gx, height), (50, 35, 20), 1)

        # Dynamic glowing circle and lines
        cx, cy = width // 2, height // 3
        r = int(120 + 20 * np.sin(t * 3.0))
        cv2.circle(img, (cx, cy), r, (245, 215, 60), 3)
        cv2.circle(img, (cx, cy), 12, (255, 255, 255), -1)

        # Crosshairs
        sweep_x = int((t * 220) % width)
        cv2.line(img, (sweep_x, 0), (sweep_x, height), (180, 140, 40), 1)

        # Text card
        cv2.putText(img, "AIMOTION // VECTOR", (60, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        cv2.putText(img, f"PHASE A // T={t:.2f}s", (60, height // 2 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 180, 50), 2)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()


def make_clip_b(out_path: Path, width: int = 720, height: int = 1280, duration: float = 3.5, fps: int = 25):
    """Generate Scene B: Solid structural architectural visual with vibrant warm lighting."""
    total_frames = int(round(duration * fps))
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(total_frames):
        t = i / float(fps)
        img = np.zeros((height, width, 3), dtype=np.uint8)
        # Warm modern studio background
        img[:, :] = [18, 22, 38]  # Rich charcoal/warm dark

        # Dynamic polygonal architectural cards
        card_y = int(height * 0.35 + 30 * np.cos(t * 2.5))
        cv2.rectangle(img, (80, card_y), (width - 80, card_y + 360), (45, 65, 120), -1)
        cv2.rectangle(img, (80, card_y), (width - 80, card_y + 360), (80, 140, 240), 3)

        # Accent badge
        badge_x = int(width * 0.5 + 80 * np.sin(t * 3.0))
        cv2.circle(img, (badge_x, card_y + 180), 60, (60, 180, 90), -1)
        cv2.circle(img, (badge_x, card_y + 180), 60, (255, 255, 255), 2)

        cv2.putText(img, "STRUCTURE // SOLID", (110, card_y + 90), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        cv2.putText(img, f"STATE B // T={t:.2f}s", (110, card_y + 260), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (100, 230, 255), 2)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()


def extract_mid_frame(video_path: Path, out_jpg: Path) -> Path:
    cap = cv2.VideoCapture(str(video_path))
    frames = []
    while True:
        ret, f = cap.read()
        if not ret or f is None:
            break
        frames.append(f)
    cap.release()

    mid_idx = len(frames) // 2
    cv2.imwrite(str(out_jpg), frames[mid_idx])
    return out_jpg


def main():
    print("Generating base 9:16 clips...")
    clip_a = SAMPLE_DIR / "base_clip_a_9x16.mp4"
    clip_b = SAMPLE_DIR / "base_clip_b_9x16.mp4"
    make_clip_a(clip_a, width=720, height=1280, duration=3.5, fps=25)
    make_clip_b(clip_b, width=720, height=1280, duration=3.5, fps=25)

    transitions = ["line_to_structure", "water_ripple", "glass_refract"]
    results = {}

    for kind in transitions:
        out_video = SAMPLE_DIR / f"sample_{kind}.mp4"
        print(f"Rendering transition sample: {kind} -> {out_video}")
        apply_transition(clip_a, clip_b, kind=kind, dur=1.2, out=out_video)

        info = probe_video(out_video)
        sha = sha256_file(out_video)

        mid_jpg = SAMPLE_DIR / f"sample_{kind}_mid.jpg"
        extract_mid_frame(out_video, mid_jpg)

        results[kind] = {
            "path": str(out_video),
            "sha256": sha,
            "duration": round(info.duration, 3),
            "total_frames": info.total_frames,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "mid_jpg": str(mid_jpg),
        }
        print(f"  {kind}: {info.width}x{info.height}, dur={info.duration:.2f}s, frames={info.total_frames}, sha256={sha[:12]}...")

    # Reframe samples from existing repo 16:9 material
    repo_interview = Path("./artifacts/real_video/20261005T160434Z/artifacts/scene_interview_720p.mp4")
    repo_broll = Path("./artifacts/real_video/20261005T160434Z/artifacts/scene_broll_720p.mp4")

    # Trim to 6s for sample brevity (<= 8s)
    trimmed_interview = SAMPLE_DIR / "src_interview_16x9_6s.mp4"
    trimmed_broll = SAMPLE_DIR / "src_broll_16x9_6s.mp4"

    subprocess.run(["ffmpeg", "-y", "-ss", "0", "-i", str(repo_interview), "-t", "6.0", "-c", "copy", str(trimmed_interview)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-ss", "0", "-i", str(repo_broll), "-t", "6.0", "-c", "copy", str(trimmed_broll)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    reframe_interview_out = SAMPLE_DIR / "sample_reframe_interview_9x16.mp4"
    reframe_broll_out = SAMPLE_DIR / "sample_reframe_broll_9x16.mp4"

    print("Reframing interview to 9:16...")
    reframe(trimmed_interview, reframe_interview_out, aspect="9:16")
    info_re_int = probe_video(reframe_interview_out)
    sha_re_int = sha256_file(reframe_interview_out)
    _, _, _, _, metrics_int = compute_reframe_windows(trimmed_interview, aspect="9:16")

    print("Reframing broll to 9:16...")
    reframe(trimmed_broll, reframe_broll_out, aspect="9:16")
    info_re_bro = probe_video(reframe_broll_out)
    sha_re_bro = sha256_file(reframe_broll_out)
    _, _, _, _, metrics_bro = compute_reframe_windows(trimmed_broll, aspect="9:16")

    results["reframe_interview"] = {
        "path": str(reframe_interview_out),
        "sha256": sha_re_int,
        "duration": round(info_re_int.duration, 3),
        "total_frames": info_re_int.total_frames,
        "width": info_re_int.width,
        "height": info_re_int.height,
        "fps": info_re_int.fps,
        "metrics": metrics_int,
    }

    results["reframe_broll"] = {
        "path": str(reframe_broll_out),
        "sha256": sha_re_bro,
        "duration": round(info_re_bro.duration, 3),
        "total_frames": info_re_bro.total_frames,
        "width": info_re_bro.width,
        "height": info_re_bro.height,
        "fps": info_re_bro.fps,
        "metrics": metrics_bro,
    }

    # Save summary json
    summary_path = SAMPLE_DIR / "samples_summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    print("\nAll samples generated successfully! Summary written to", summary_path)


if __name__ == "__main__":
    main()
