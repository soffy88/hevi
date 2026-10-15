"""生成样片脚本：使用本地 CPU (PIL + ffmpeg) 渲染两支 6-20s 1080p 成片 (16:9 与 9:16 各一)，保存至 audit/storyplan/samples/。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def render_sample(output_path: Path, width: int, height: int, title: str, subtitle: str, duration_sec: int = 10) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fps = 30
    total_frames = duration_sec * fps
    tmp_frames_dir = output_path.parent / f"tmp_{output_path.stem}"
    tmp_frames_dir.mkdir(exist_ok=True)

    print(f"Rendering {output_path.name} ({width}x{height}, {duration_sec}s)...")
    for i in range(total_frames):
        img = Image.new("RGB", (width, height), color=(240, 248, 255))
        draw = ImageDraw.Draw(img)
        
        # 绘制背景装饰与进度条
        progress = i / max(1, total_frames - 1)
        bar_w = int(width * 0.8 * progress)
        draw.rectangle([int(width * 0.1), int(height * 0.85), int(width * 0.1) + bar_w, int(height * 0.88)], fill=(70, 130, 180))
        
        # 动态圆圈代表主角/动画实体
        cx = int(width * 0.1 + (width * 0.8) * progress)
        cy = int(height * 0.5 + 30 * (-1 if (i // 15) % 2 == 0 else 1))
        draw.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], fill=(255, 165, 0), outline=(255, 140, 0), width=4)
        
        # 绘制文字
        draw.text((int(width * 0.1), int(height * 0.15)), f"HEVI StoryPlan: {title}", fill=(25, 25, 112))
        draw.text((int(width * 0.1), int(height * 0.75)), f"字幕: {subtitle} (t={i/fps:.1f}s)", fill=(0, 100, 0))

        frame_file = tmp_frames_dir / f"frame_{i:04d}.png"
        img.save(frame_file)

    # 用 ffmpeg 合成 mp4
    cmd = [
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(tmp_frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", str(duration_sec),
        str(output_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 清理临时帧
    for f in tmp_frames_dir.glob("*.png"):
        f.unlink()
    tmp_frames_dir.rmdir()


def main() -> None:
    samples_dir = Path("audit/storyplan/samples")
    samples_dir.mkdir(parents=True, exist_ok=True)

    s1 = samples_dir / "raindrop_16_9.mp4"
    render_sample(s1, 1920, 1080, "小水滴去哪儿了", "小水滴变成白云又落回小河", 10)

    s2 = samples_dir / "bear_9_16.mp4"
    render_sample(s2, 1080, 1920, "小熊为什么洗手", "饭前洗净小手 远离细菌健康成长", 10)

    # 生成 ffprobe 报告与 sha256
    report = {}
    for sp in [s1, s2]:
        sha = hashlib.sha256(sp.read_bytes()).hexdigest()
        ff_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(sp)]
        res = subprocess.run(ff_cmd, capture_output=True, text=True)
        probe_info = json.loads(res.stdout) if res.returncode == 0 else {}
        report[sp.name] = {
            "sha256": sha,
            "size_bytes": sp.stat().st_size,
            "ffprobe": probe_info,
        }

    meta_file = samples_dir / "samples_meta.json"
    meta_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Samples generated successfully and meta written to {meta_file}")


if __name__ == "__main__":
    main()
