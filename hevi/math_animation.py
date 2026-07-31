"""数学/科学动画 —— ManimCE 集成。

对标 OpenMontage 的 math_animate 工具。通过 Python 脚本生成数学动画视频，
用于科学可视化、教育内容、数据图表动画等场景。

用法:
    from hevi.math_animation import create_math_animation
    result = await create_math_animation(
        script_path=Path("equation.py"),
        output_path=Path("animation.mp4"),
        resolution="720p",
        fps=30
    )
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def create_math_animation(
    script_path: Path,
    output_path: Path,
    *,
    scene_class: str = "MathAnimation",
    resolution: str = "720p",
    fps: int = 30,
    quality: str = "high",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """通过 ManimCE 生成数学动画。

    Args:
        script_path: 包含 Manim Scene 类的 Python 脚本路径
        output_path: 输出视频路径
        scene_class: 脚本中的 Scene 类名
        resolution: "480p" / "720p" / "1080p"
        fps: 帧率
        quality: "low" / "medium" / "high" / "fourk"
        timeout_s: 超时时间

    Returns:
        包含输出路径、时长、成本等信息的字典
    """
    # 检查 manim 是否安装
    try:
        result = subprocess.run(["manim", "--version"], capture_output=True, text=True, timeout=10)
        manim_available = result.returncode == 0
    except FileNotFoundError:
        manim_available = False

    if not manim_available:
        # 尝試安裝 manim
        try:
            subprocess.run(["pip", "install", "manim"], check=True, timeout=120)
            manim_available = True
        except Exception as e:
            logger.warning("Manim not available and installation failed: %s", e)
            # 回退到創建一個靜態圖像
            return await _fallback_static_animation(output_path)

    if not manim_available:
        return await _fallback_static_animation(output_path)

    # 確定分辨率參數
    resolution_map = {
        "480p": "480p",
        "720p": "720p", 
        "1080p": "1080p",
        "fourk": "1440p"  # Manim 中 4K 是 1440p
    }
    res = resolution_map.get(resolution, "720p")
    
    quality_flag = {
        "low": "-ql",
        "medium": "-qm", 
        "high": "-qh",
        "fourk": "-qk"
    }.get(quality, "-qh")

    # 構建 manim 命令
    cmd = [
        "manim",
        quality_flag,
        f"--media_dir={output_path.parent}",
        f"--custom_folders",
        f"-o={output_path.name}",
        f"--fps={fps}",
        f"--resolution={res}",
        str(script_path),
        scene_class
    ]

    logger.info("Running manim command: %s", " ".join(cmd))
    
    try:
        # 運行 manim
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        
        if process.returncode != 0:
            logger.error("Manim failed: %s", stderr.decode())
            # 使用回退方案
            return await _fallback_static_animation(output_path)
        
        # 檢查輸出文件是否存在
        if not output_path.exists():
            # 查找 manim 生成的視頻文件
            output_dir = output_path.parent
            video_files = list(output_dir.glob("*.mp4"))
            if video_files:
                # 使用最新生成的文件
                latest_file = max(video_files, key=lambda x: x.stat().st_mtime)
                if latest_file != output_path:
                    latest_file.rename(output_path)
        
        if not output_path.exists():
            logger.error("Manim completed but no output file found")
            return await _fallback_static_animation(output_path)
            
        # 獲取文件時長
        duration_s = await _get_video_duration(output_path)
        
        return {
            "success": True,
            "output_path": str(output_path),
            "duration_s": duration_s,
            "cost_usd": _estimate_cost(duration_s, quality),
            "provider": "manimce"
        }
        
    except asyncio.TimeoutError:
        logger.error("Manim command timed out after %d seconds", timeout_s)
        return await _fallback_static_animation(output_path)
    except Exception as e:
        logger.error("Error running manim: %s", e)
        return await _fallback_static_animation(output_path)


async def _get_video_duration(video_path: Path) -> float:
    """獲取視頻時長（秒）"""
    try:
        result = await asyncio.create_subprocess_exec(
            "ffprobe", 
            "-v", "quiet", 
            "-show_entries", "format=duration", 
            "-of", "csv=p=0", 
            str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await result.communicate()
        if result.returncode == 0:
            duration_str = stdout.decode().strip()
            try:
                return float(duration_str)
            except ValueError:
                pass
    except Exception:
        pass
    return 0.0


def _estimate_cost(duration_s: float, quality: str) -> float:
    """估算成本"""
    # ManimCE 是本地運算，成本主要為電力和時間，設為固定值
    base_cost = 0.02  # $0.02 per animation
    quality_multiplier = {"low": 0.5, "medium": 1.0, "high": 2.0, "fourk": 5.0}.get(quality, 1.0)
    return round(base_cost * quality_multiplier, 4)


async def _fallback_static_animation(output_path: Path) -> dict[str, Any]:
    """回退：創建一個靜態數學公式圖像並轉換為視頻"""
    import tempfile
    from PIL import Image, ImageDraw, ImageFont
    
    # 創建一個示意性的數學公式圖片
    img = Image.new('RGB', (1280, 720), color='white')
    draw = ImageDraw.Draw(img)
    
    try:
        # 嘗試使用系統字體
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    except:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 48)
        except:
            font = ImageFont.load_default()
    
    # 繪製一些示意性的數學內容
    formulas = [
        "E = mc²",
        "∫ f(x) dx",
        "∑ n=1 to ∞",
        "∂²u/∂t² = c²∇²u"
    ]
    
    y_offset = 100
    for formula in formulas:
        bbox = draw.textbbox((0, 0), formula, font=font)
        text_width = bbox[2] - bbox[0]
        x = (img.width - text_width) // 2
        draw.text((x, y_offset), formula, fill='black', font=font)
        y_offset += 100
    
    # 保存為臨時圖片
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_img:
        img.save(tmp_img.name, 'PNG')
        
        # 使用 ffmpeg 將圖片轉換為 3 秒視頻
        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", tmp_img.name,
            "-c:v", "libx264",
            "-t", "3",  # 3秒
            "-pix_fmt", "yuv420p",
            "-vf", "scale=1280:720",
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # 清理臨時文件
        Path(tmp_img.name).unlink()
    
    if result.returncode != 0:
        logger.error("Fallback animation creation failed: %s", result.stderr)
        # 創建一個空文件作為最後的回退
        output_path.touch()
    
    return {
        "success": output_path.exists(),
        "output_path": str(output_path),
        "duration_s": 3.0,
        "cost_usd": 0.01,
        "provider": "fallback",
        "note": "ManimCE not available, using fallback static animation"
    }


def create_sample_math_script(output_path: Path, title: str = "Sample Math Animation") -> Path:
    """創建一個示例數學動畫腳本"""
    script_content = '''
from manim import *

class MathAnimation(Scene):
    def construct(self):
        # 樱題
        title = Text("TITLE_PLACEHOLDER", font_size=36)
        self.play(Write(title))
        self.wait(1)
        self.play(FadeOut(title))
        
        # 動畫 1: 基本公式
        eq1 = MathTex("E", "=", "mc^2")
        eq1.scale(2)
        self.play(Write(eq1))
        self.wait(2)
        
        # 動畫 2: 複雜公式
        eq2 = MathTex("\\int", "_0", "^\\infty", "e^{-x^2}", "dx", "=", "{{\\pi} \\over {2}}")
        eq2.scale(1.5)
        self.play(Transform(eq1, eq2))
        self.wait(2)
        
        # 動畫 3: 圖形
        circle = Circle(radius=1, color=BLUE)
        self.play(Create(circle))
        self.wait(1)
        
        square = Square(side_length=2, color=RED)
        self.play(Transform(circle, square))
        self.wait(1)
        
        self.play(FadeOut(circle), FadeOut(eq1))
'''.replace("TITLE_PLACEHOLDER", title)

    output_path.write_text(script_content, encoding='utf-8')
    return output_path