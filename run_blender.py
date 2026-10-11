import asyncio
from pathlib import Path
from hevi.creative.layer4.blender_workflow import blender_render_workflow
import subprocess
import os

env = os.environ.copy()
env["PATH"] = f"/home/soffy/.local/bin:{env.get('PATH', '')}"
out = Path("output/om_render_e2e")
blender_render_workflow(
    shot_spec={"width": 1280, "height": 720, "fps": 24, "frame_end": 120, "objects": [{"type": "cube", "name": "cube1"}]},
    blender_binary="/home/soffy/opt/blender/blender",
    output_path=str(out / "blender_shot.png")
)
subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(out / "blender_shot.png"), "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-vf", "scale=1280:720", str(out / "blender_shot.mp4")], env=env, check=True)
subprocess.run(["ffmpeg", "-y", "-i", str(out / "blender_shot.mp4"), "-vf", "fps=1,scale=320:-1,tile=4x4", str(out / "blender_shot.mp4.jpg")], env=env, check=False)
