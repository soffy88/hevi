"""荆轲刺秦王 — 文字电影生成器。

使用 PIL 渲染帧 + FFmpeg 编码 MP4。
6 场景, 每场景 5-8 秒, 总时长约 45 秒。
"""
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ─── 配置 ───
W, H, FPS = 1920, 1080, 30
OUTPUT = Path("/data/soffy/projects/hevi/outputs/jingke")
FRAMES_DIR = OUTPUT / "frames"
FINAL_MP4 = OUTPUT / "荆轲刺秦王.mp4"

FONT_PATHS = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
]
FONT_PATH = next((p for p in FONT_PATHS if os.path.exists(p)), None)


def font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, size)
    return ImageFont.load_default()


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def text_size(draw: ImageDraw.Draw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple:
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_centered(draw: ImageDraw.Draw, text: str, y: int, fnt: ImageFont.FreeTypeFont, color: str, alpha: float):
    if alpha <= 0:
        return
    tw, _ = text_size(draw, text, fnt)
    x = (W - tw) // 2
    r, g, b = hex_to_rgb(color)
    a = int(255 * min(1.0, max(0.0, alpha)))
    draw.text((x, y), text, font=fnt, fill=(r, g, b, a))


def fade_alpha(t: float, start: float, end: float, fade_in: float = 1.0, fade_out: float = 1.0) -> float:
    """计算淡入淡出透明度。"""
    if t < start or t > end:
        return 0.0
    if t < start + fade_in:
        return (t - start) / fade_in
    if t > end - fade_out:
        return (end - t) / fade_out
    return 1.0


# ─── 场景定义 ───

SCENES = [
    {
        "name": "开场",
        "duration": 6,
        "bg": "#0a0a0a",
        "lines": [
            {"text": "荆 轲 刺 秦 王", "size": 96, "color": "#d4af37", "y": 420, "start": 0.5, "end": 5.5},
            {"text": "— 公元前227年 —", "size": 36, "color": "#888888", "y": 560, "start": 1.5, "end": 5.5},
        ],
    },
    {
        "name": "易水送别",
        "duration": 8,
        "bg": "#0d1a0d",
        "lines": [
            {"text": "易 水 送 别", "size": 72, "color": "#c0d8c0", "y": 180, "start": 0.5, "end": 7.5},
            {"text": "太子丹率百官白衣冠送行至易水之畔", "size": 32, "color": "#8aaa8a", "y": 300, "start": 1.5, "end": 7.5},
            {"text": "风 萧 萧 兮 易 水 寒", "size": 64, "color": "#ffffff", "y": 440, "start": 3.0, "end": 7.5},
            {"text": "壮 士 一 去 兮 不 复 还", "size": 64, "color": "#ffd700", "y": 540, "start": 4.0, "end": 7.5},
            {"text": "高渐离击筑  荆轲和而歌  士皆垂泪", "size": 28, "color": "#6a8a6a", "y": 680, "start": 5.5, "end": 7.5},
        ],
    },
    {
        "name": "入秦宫",
        "duration": 7,
        "bg": "#1a100a",
        "lines": [
            {"text": "入  秦", "size": 80, "color": "#d4af37", "y": 160, "start": 0.5, "end": 6.5},
            {"text": "荆轲携督亢地图与樊於期首级", "size": 34, "color": "#aa8844", "y": 290, "start": 1.5, "end": 6.5},
            {"text": "以燕国使臣之名  踏入咸阳宫", "size": 34, "color": "#aa8844", "y": 345, "start": 2.5, "end": 6.5},
            {"text": "秦王政  端坐龙椅之上", "size": 44, "color": "#ffcc66", "y": 470, "start": 3.5, "end": 6.5},
            {"text": "文武百官  肃立两侧", "size": 32, "color": "#886644", "y": 570, "start": 4.5, "end": 6.5},
            {"text": "一场千古壮剧  即将上演", "size": 28, "color": "#665533", "y": 660, "start": 5.5, "end": 6.5},
        ],
    },
    {
        "name": "图穷匕见",
        "duration": 8,
        "bg": "#1a0a0a",
        "lines": [
            {"text": "图 穷 匕 见", "size": 80, "color": "#ff4444", "y": 150, "start": 0.5, "end": 7.5},
            {"text": "荆轲取图奉之  秦王发图", "size": 34, "color": "#cc8888", "y": 290, "start": 1.5, "end": 7.5},
            {"text": "图穷而匕首见", "size": 56, "color": "#ffffff", "y": 400, "start": 3.0, "end": 7.5},
            {"text": "左手把秦王之袖", "size": 42, "color": "#ffcc00", "y": 520, "start": 4.5, "end": 7.5},
            {"text": "右手持匕首揕之", "size": 42, "color": "#ff6600", "y": 590, "start": 5.0, "end": 7.5},
            {"text": "未至身  秦王惊  自引而起  绝袖", "size": 28, "color": "#996666", "y": 700, "start": 6.0, "end": 7.5},
        ],
    },
    {
        "name": "逐秦王",
        "duration": 8,
        "bg": "#0a0a2a",
        "lines": [
            {"text": "逐 秦 王", "size": 80, "color": "#4488ff", "y": 150, "start": 0.5, "end": 7.5},
            {"text": "秦王惊起  袖绝  拔剑", "size": 36, "color": "#88aaff", "y": 290, "start": 1.5, "end": 7.5},
            {"text": "剑长  操其室  惶急  剑坚  故不可立拔", "size": 28, "color": "#6688aa", "y": 350, "start": 2.5, "end": 7.5},
            {"text": "二人绕柱奔走", "size": 56, "color": "#ffffff", "y": 460, "start": 3.5, "end": 7.5},
            {"text": "群臣愕然  莫知所为", "size": 36, "color": "#6688aa", "y": 580, "start": 5.0, "end": 7.5},
            {"text": "夏无且以药囊击荆轲  王负剑  遂拔以击轲", "size": 26, "color": "#556688", "y": 670, "start": 5.5, "end": 7.5},
        ],
    },
    {
        "name": "英雄落幕",
        "duration": 9,
        "bg": "#0a0a0a",
        "lines": [
            {"text": "英 雄 末 路", "size": 72, "color": "#888888", "y": 150, "start": 0.5, "end": 8.5},
            {"text": "秦王拔剑斩荆轲  断其左股", "size": 34, "color": "#aa6666", "y": 280, "start": 1.5, "end": 8.5},
            {"text": "荆轲废  乃引其匕首提秦王  不中  中柱", "size": 28, "color": "#998877", "y": 340, "start": 2.5, "end": 8.5},
            {"text": "荆轲倚柱而笑  箕踞以骂", "size": 48, "color": "#ffd700", "y": 430, "start": 4.0, "end": 8.5},
            {"text": "事所以不成者", "size": 40, "color": "#ccccaa", "y": 540, "start": 5.0, "end": 8.5},
            {"text": "乃欲以生劫之  必得约契以报太子也", "size": 32, "color": "#aaaaaa", "y": 600, "start": 5.5, "end": 8.5},
            {"text": "— 太史公《史记 · 刺客列传》—", "size": 24, "color": "#666666", "y": 700, "start": 6.5, "end": 8.5},
            {"text": "THE  END", "size": 48, "color": "#444444", "y": 800, "start": 7.5, "end": 8.5},
        ],
    },
]


def render_scene_frames(scene: dict, scene_idx: int) -> list[Path]:
    """渲染单个场景的所有帧。"""
    name = scene["name"]
    dur = scene["duration"]
    bg = hex_to_rgb(scene["bg"])
    lines = scene["lines"]
    total_frames = int(dur * FPS)

    scene_dir = FRAMES_DIR / f"scene_{scene_idx}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    title_font = font(lines[0]["size"])
    fonts_cache = {}

    for frame_idx in range(total_frames):
        t = frame_idx / FPS  # current time in seconds

        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)

        # 绘制场景分隔线 (底部装饰线)
        line_color = tuple(min(255, c + 30) for c in bg)
        draw.line([(W // 2 - 200, H - 40), (W // 2 + 200, H - 40)], fill=line_color, width=2)

        for line_def in lines:
            fnt_size = line_def["size"]
            if fnt_size not in fonts_cache:
                fonts_cache[fnt_size] = font(fnt_size)
            fnt = fonts_cache[fnt_size]

            alpha = fade_alpha(t, line_def["start"], line_def["end"])
            if alpha > 0:
                draw_centered(draw, line_def["text"], line_def["y"], fnt, line_def["color"], alpha)

        # 保存帧
        frame_path = scene_dir / f"frame_{frame_idx:04d}.png"
        img.save(frame_path, optimize=True)

    return list(scene_dir.glob("frame_*.png"))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if FRAMES_DIR.exists():
        shutil.rmtree(FRAMES_DIR)
    FRAMES_DIR.mkdir()

    print("🎬 生成《荆轲刺秦王》文字电影...")
    print(f"   分辨率: {W}x{H}  FPS: {FPS}")
    print()

    all_frames: list[Path] = []

    for i, scene in enumerate(SCENES):
        print(f"  Scene {i+1}/{len(SCENES)}: {scene['name']} ({scene['duration']}s)...")
        frames = render_scene_frames(scene, i)
        all_frames.extend(frames)
        print(f"    → {len(frames)} frames")

    total_sec = sum(s["duration"] for s in SCENES)
    print(f"\n  总计: {len(all_frames)} frames, ~{total_sec}s")

    # 创建 FFmpeg concat 列表 (使用帧序列)
    print("\n🔗 编码为 MP4...")

    # 将所有帧按顺序排列到一个目录
    concat_dir = FRAMES_DIR / "concat"
    concat_dir.mkdir()
    for idx, frame_path in enumerate(all_frames):
        ext = frame_path.suffix
        (concat_dir / f"frame_{idx:05d}{ext}").symlink_to(frame_path.resolve())

    # FFmpeg 编码
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(concat_dir / "frame_%05d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "20",
        "-vf", f"scale={W}:{H}",
        "-movflags", "+faststart",
        str(FINAL_MP4),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ FFmpeg 失败: {result.stderr[-500:]}")
        return

    # 输出信息
    size_mb = FINAL_MP4.stat().st_size / 1024 / 1024
    print(f"\n✅ 完成!")
    print(f"  📁 文件: {FINAL_MP4}")
    print(f"  ⏱️  时长: {total_sec}s ({total_sec // 60}:{total_sec % 60:02d})")
    print(f"  📐 分辨率: {W}x{H}")
    print(f"  💾 大小: {size_mb:.1f} MB")
    print(f"  🎬 场景: {len(SCENES)} 个")


if __name__ == "__main__":
    main()
