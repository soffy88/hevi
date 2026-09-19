#!/usr/bin/env python3
"""D3-F: lip-sync runtime qualification probe (fail-closed, no monitoring).

Re-running D2-A is allowed ONLY when every field below is satisfied::

    GPU_AVAILABLE=true, COMFYUI_REACHABLE=true, ECHOMIMIC_AVAILABLE=true,
    MODEL_AVAILABLE=true, REAL_PROBE=executed, ARTIFACT_VALID=true

Anything else keeps D2-A BLOCKED. A BLOCKED result is a hardware/runtime
statement, never a HEVI architecture failure. Uses only stdlib (+ project
venv for the optional real probe); never installs models or daemons.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "artifacts" / "qualification" / "lipsync_runtime_probe.json"
COMFY_URL = "http://127.0.0.1:8188"
WORKFLOW = (
    REPO / "hevi" / "providers" / "echo_mimic" / "workflows" / "echomimic_v2_10g.json"
)


def _run(command: list[str], timeout: int = 15) -> dict[str, object]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[:800],
            "stderr": result.stderr.strip()[:800],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": None, "stdout": "", "stderr": type(exc).__name__}


def _http_json(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read(65536)
            return True, f"HTTP_{response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP_{exc.code}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, type(exc).__name__


def collect(*, real_probe: bool = False) -> dict[str, object]:
    nvidia_smi = (
        _run(["nvidia-smi", "-L"], timeout=20)
        if shutil.which("nvidia-smi")
        else {"returncode": None, "stdout": "", "stderr": "nvidia-smi unavailable"}
    )
    smi_text = f"{nvidia_smi['stdout']}\n{nvidia_smi['stderr']}".lower()
    gpu_available = (
        nvidia_smi["returncode"] == 0
        and "no devices were found" not in smi_text
        and "unable to determine the device handle" not in smi_text
    )

    comfy_ok, comfy_detail = _http_json(COMFY_URL.rstrip("/") + "/system_stats")
    workflow_present = WORKFLOW.exists()
    echomimic_available = bool(comfy_ok and workflow_present)
    model_available = bool(workflow_present)

    result: dict[str, object] = {
        "probed_at": datetime.now(UTC).isoformat(),
        "GPU_AVAILABLE": gpu_available,
        "NVIDIA_SMI": nvidia_smi,
        "COMFYUI_REACHABLE": comfy_ok,
        "COMFYUI_DETAIL": comfy_detail,
        "ECHOMIMIC_AVAILABLE": echomimic_available,
        "MODEL_AVAILABLE": model_available,
        "WORKFLOW_PATH": str(WORKFLOW),
        "REAL_PROBE": "SKIPPED",
        "ARTIFACT_VALID": False,
        "D2A_REOPEN_ALLOWED": False,
    }

    ready = all([gpu_available, comfy_ok, echomimic_available, model_available])
    if not ready:
        result["REAL_PROBE"] = "SKIPPED_BLOCKED"
        result["BLOCKER"] = (
            "D2-A stays BLOCKED: "
            + ", ".join(
                name
                for name, ok in (
                    ("GPU", gpu_available),
                    ("COMFYUI", comfy_ok),
                    ("ECHOMIMIC", echomimic_available),
                    ("MODEL", model_available),
                )
                if not ok
            )
        )
        result["LIPSYNC_BLOCKER"] = result["BLOCKER"]
        return result

    if not real_probe:
        result["REAL_PROBE"] = "SKIPPED_READY_NO_PROBE"
        result["NOTE"] = "Runtime ready; re-run with --real-probe to execute D2-A evidence."
        return result

    # Real probe: image + audio through the production talking-face entry.
    result["REAL_PROBE"] = "EXECUTED"
    try:
        probe_dir = REPO / "artifacts" / "qualification" / "lipsync_probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        image_path = probe_dir / "probe_face.png"
        audio_path = probe_dir / "probe_speech.wav"
        output_path = probe_dir / "probe_out.mp4"
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from PIL import Image; "
                "Image.new('RGB',(256,256),(200,150,120)).save(r'%s')" % image_path,
            ],
            check=True,
            timeout=60,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=3",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(audio_path),
            ],
            check=True,
            timeout=60,
        )
        venv_python = REPO / ".venv" / "bin" / "python"
        proc = subprocess.run(
            [
                str(venv_python),
                "-c",
                "import asyncio;from hevi.digital_human import talking_face as tf;"
                "asyncio.run(tf.generate_talking_face("
                f"image_path=r'{image_path}',audio_path=r'{audio_path}',"
                f"output_path=r'{output_path}'))",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        result["PROBE_RETURNCODE"] = proc.returncode
        result["PROBE_STDERR_TAIL"] = proc.stderr.strip()[-800:]
        if proc.returncode == 0 and output_path.exists():
            probe = _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,width,height,r_frame_rate,duration",
                    "-of",
                    "json",
                    str(output_path),
                ]
            )
            try:
                streams = json.loads(str(probe["stdout"] or "{}")).get("streams", [])
            except json.JSONDecodeError:
                streams = []
            kinds = {str(s.get("codec_type")) for s in streams}
            valid = "video" in kinds and "audio" in kinds and output_path.stat().st_size > 0
            result["ARTIFACT_VALID"] = bool(valid)
            result["ARTIFACT_PATH"] = str(output_path)
            result["D2A_REOPEN_ALLOWED"] = bool(valid)
        else:
            result["ARTIFACT_VALID"] = False
    except (OSError, subprocess.SubprocessError) as exc:
        result["REAL_PROBE"] = f"PROBE_ERROR:{type(exc).__name__}"
        result["ARTIFACT_VALID"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-probe", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    result = collect(real_probe=args.real_probe)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
