#!/usr/bin/env python3
"""Run the Remotion/HyperFrames compatibility qualification.

The command intentionally does not call the HyperFrames provider when its CLI
is absent: the provider's production fallback is valid for ordinary rendering,
but it is not evidence that the requested HyperFrames runtime executed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from hevi.assembly.runtime_interop import qualify_runtime_interop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/hevi-runtime-interop"))
    args = parser.parse_args()
    image_path = Path(__file__).resolve().parents[1] / "data/cinematic_output/ep01_beijingren/kf_00.png"
    audio_path = Path(__file__).resolve().parents[1] / "data/workspace/a255e884-3037-4dc2-b667-8e22746be7cb/bgm.wav"
    scene: dict[str, Any] = {
        "composition_id": "MotionGraphics",
        "width": 640,
        "height": 360,
        "fps": 30,
        "duration_frames": 90,
        "title": "HEVI runtime interop qualification",
        "spec": {
            "composition_id": "MotionGraphics",
            "width": 640,
            "height": 360,
            "fps": 30,
            "duration_frames": 90,
            "layers": [],
        },
    }
    if image_path.is_file():
        scene["spec"]["layers"] = [{
            "id": "qualification-image",
            "type": "image",
            "src": "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "x": 50,
            "y": 50,
            "start_frame": 0,
            "end_frame": 90,
            "animation": "scale",
            "scene": "image-text",
        }]
    if audio_path.is_file():
        scene["audio_src"] = "data:audio/wav;base64," + base64.b64encode(audio_path.read_bytes()).decode("ascii")
    report = asyncio.run(qualify_runtime_interop(
        scene=scene,
        output_dir=args.output_dir,
        project_dir=Path(__file__).resolve().parents[1] / "hevi-remotion",
    ))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 0 if report.verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
