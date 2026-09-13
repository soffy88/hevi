#!/usr/bin/env python3
"""Inventory provider implementations and their line dependencies without secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

ENV_VARS: dict[str, list[str]] = {
    "llm": ["OPENAI_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY", "ANTHROPIC_API_KEY"],
    "tts": ["EDGE_TTS_VOICE", "TTS_API_KEY", "ELEVENLABS_API_KEY"],
    "media_source": ["PEXELS_API_KEY", "PIXABAY_API_KEY", "MATERIAL_CACHE_DIR"],
    "h3_local": ["H3_ROUTING", "H3_COMFY_URL", "H3_WORKFLOWS_DIR"],
    "ComfyUI/local_gpu_backend": ["H3_COMFY_URL"],
    "remotion": ["REMOTION_ENTRY", "REMOTION_COMPOSITION"],
    "hyperframes": ["HYPERFRAMES_BIN", "HYPERFRAMES_QUALITY"],
    "ffmpeg": [],
    "manim": [],
}


def _line_requirements() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(Path("hevi/studio/lines").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tools = {str(item) for item in data.get("tools", [])}
        providers = {str(data.get("render_runtime", ""))}
        if any(item.startswith(("research.", "script.", "score.")) for item in tools):
            providers.add("llm")
        if any(item.startswith(("tts.", "audio.", "dub.")) for item in tools):
            providers.add("tts")
        if any(item.startswith(("material.", "watch.", "ingest.")) for item in tools):
            providers.add("media_source")
        if any("h3" in item or "avatar" in item for item in tools):
            providers.add("h3_local")
        result[str(data["id"])] = sorted(item for item in providers if item)
    return result


def collect() -> dict[str, Any]:
    required = _line_requirements()
    names: set[str] = set()
    names.update(required_name for values in required.values() for required_name in values)
    names.update(ENV_VARS)
    records = []
    for name in sorted(names):
        module_candidates = [
            Path("hevi/providers") / name / "provider.py",
            Path("hevi/providers") / name / "__init__.py",
            Path("hevi/video") / f"provider_{name}.py",
        ]
        capability = any(path.exists() for path in module_candidates) or name in {"llm", "tts", "media_source", "ffmpeg", "remotion"}
        endpoint = os.getenv("H3_COMFY_URL") if name in {"h3_local", "ComfyUI/local_gpu_backend"} else None
        records.append({
            "provider": name,
            "capability": capability,
            "env_vars": ENV_VARS.get(name, []),
            "endpoint": endpoint,
            "local": name not in {"llm", "media_source"},
            "required_by_lines": sorted(line for line, providers in required.items() if name in providers),
            "auth_probe_supported": name in {"llm", "media_source"},
            "real_generation_probe_supported": name in {"llm", "tts", "media_source", "remotion", "hyperframes", "h3_local", "ComfyUI/local_gpu_backend"},
        })
    return {"providers": records, "line_dependencies": required}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/provider_inventory.json"))
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
