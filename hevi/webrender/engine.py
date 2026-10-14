"""
Hevi WebRender Engine: Headless Playwright Chromium (SwiftShader) frame renderer and FFmpeg encoder.
"""

import asyncio
import os
import subprocess
import tempfile
from typing import List, Optional
from playwright.async_api import async_playwright

class WebRenderEngine:
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps

    async def render_frames(self, html_path: str, duration: float, output_dir: str) -> List[str]:
        os.makedirs(output_dir, exist_ok=True)
        total_frames = int(duration * self.fps)
        frame_paths = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--use-gl=swiftshader",
                    "--enable-unsafe-swiftshader",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )
            context = await browser.new_context(
                viewport={"width": self.width, "height": self.height}
            )
            page = await context.new_page()
            
            abs_url = f"file://{os.path.abspath(html_path)}"
            await page.goto(abs_url, wait_until="networkidle")

            # Render frames concurrently or sequentially with precise seek
            for i in range(total_frames):
                t = i / self.fps
                # Invoke __setTime(t) if defined in page, else evaluate time
                try:
                    await page.evaluate(f"if (typeof __setTime === 'function') {{ __setTime({t}); }}")
                except Exception:
                    pass
                
                # Small wait for DOM update / animation tick
                await page.wait_for_timeout(10)
                
                frame_path = os.path.join(output_dir, f"frame_{i:05d}.png")
                await page.screenshot(path=frame_path)
                frame_paths.append(frame_path)

            await browser.close()
        return frame_paths

    def encode_video(self, frame_pattern: str, output_mp4: str, fps: int = 30) -> str:
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", frame_pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            output_mp4
        ]
        result = subprocess.run(cmd, capturejsonplaceholder=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg encoding failed: {result.stderr}")
        return output_mp4
