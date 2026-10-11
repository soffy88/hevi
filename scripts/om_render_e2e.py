import os
import shutil
from pathlib import Path
from hevi.studio.fulfill import _render_character_animation_line, _render_hyperframes_line
from hevi.providers.hyperframes.provider import hyperframes_styled_generate
from hevi.creative.layer4.blender_workflow import blender_render_workflow
import asyncio
import subprocess

env = os.environ.copy()
env["PATH"] = f"/home/soffy/.local/bin:{env.get('PATH', '')}"

async def main():
    out = Path("output/om_render_e2e")
    out.mkdir(parents=True, exist_ok=True)
    
    script_lines = [
        "KV Cache 是大语言模型推理中的核心优化技术。",
        "在生成文本时，模型需要逐字预测下一个词。",
        "如果没有 KV Cache，每次预测都需要重新计算之前所有词的 Attention，极其耗时。",
        "通过将之前的 Key 和 Value 缓存下来，只需要计算当前词的 Query，",
        "极大降低了计算复杂度，提高了生成速度和效率。"
    ]
    
    styles = ["v6-cinematic", "v8-chalkboard", "v4-paper", "v9-clay"]
    
    for i, style in enumerate(styles):
        print(f"Generating Hyperframes style {style}...")
        try:
            await hyperframes_styled_generate(
                prompt={"topic": "KV Cache 机制解析", "script_lines": script_lines},
                output_path=out / f"hf_{style}.mp4",
                config={"style": style}
            )
        except Exception as e:
            print(f"Failed to generate style {style}: {e}")

    # Character animation
    print("Generating Character animation...")
    try:
        await _render_character_animation_line(
            order={"line_id": "char_anim_test"},
            context={},
            output_dir=out
        )
    except Exception as e:
        print(f"Failed character animation: {e}")
    
    # Blender shot
    print("Generating Blender shot...")
    try:
        blender_render_workflow(
            shot_spec={"width": 1280, "height": 720, "fps": 24, "frame_end": 120, "objects": [{"type": "cube", "name": "cube1"}]},
            blender_binary="/home/soffy/opt/blender/blender",
            output_path=str(out / "blender_shot.png")
        )
        # convert png to short mp4
        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(out / "blender_shot.png"), "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-vf", "scale=1280:720", str(out / "blender_shot.mp4")], env=env, check=True)
    except Exception as e:
        print(f"Failed Blender: {e}")
    
    def contact(mp4):
        mp4_path = out / mp4
        if mp4_path.exists():
            subprocess.run(["ffmpeg", "-y", "-i", str(mp4_path), "-vf", "fps=1,scale=320:-1,tile=4x4", str(out / f"{mp4}.jpg")], env=env, check=False)
            subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", str(mp4_path)], env=env, check=False)
            
    for style in styles:
        contact(f"hf_{style}.mp4")
    contact("character_animation.mp4")
    contact("blender_shot.mp4")
    
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
