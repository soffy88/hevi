"""SVFACTORY Batch Preset Production & Breakpoint Resume module.

Processes batch generation tasks from presets:
- Serial execution (CPU-only)
- Breakpoint resume (skips already rendered outputs with valid manifest)
- Independent manifest + kids_gate validation per video
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hevi.svfactory.renderer import render_svfactory_episode


class BatchRunner:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.batch_id = config.get("batch_id", f"batch_{int(time.time())}")
        self.topics = config.get("topics", ["分享", "轮流", "情绪识别"])
        self.output_dir = Path(config.get("output_dir", "output/svfactory"))
        self.asset_dir = config.get("asset_dir")
        self.aspect = config.get("aspect", "16:9")
        self.seed = int(config.get("seed", 42))
        self.voice = config.get("voice", "zh_CN-huayan-medium.onnx")
        self.bgm_path = config.get("bgm_path")
        self.state_file = self.output_dir / f"{self.batch_id}_state.json"

    async def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        total = len(self.topics)
        completed = 0
        failed = 0
        results = []

        state = {
            "batch_id": self.batch_id,
            "total": total,
            "completed": 0,
            "failed": 0,
            "running": True,
            "items": [],
        }
        self._save_state(state)

        for idx, topic in enumerate(self.topics, 1):
            out_name = f"episode_{idx:03d}_{topic}.mp4"
            out_path = self.output_dir / out_name
            manifest_path = out_path.with_suffix(".manifest.json")

            # Breakpoint resume check: if mp4 and manifest exist and gate passed, skip
            if out_path.exists() and manifest_path.exists():
                try:
                    m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if m_data.get("gate_passed"):
                        completed += 1
                        results.append(m_data)
                        state["completed"] = completed
                        state["items"].append({"topic": topic, "status": "resumed", "path": str(out_path)})
                        self._save_state(state)
                        continue
                except Exception:
                    pass

            try:
                script_text = f"宝宝快看，今天我们要学习关于「{topic}」的小故事。大家要互相帮助，开开心心每一天！"
                manifest = await render_svfactory_episode(
                    script_text=script_text,
                    asset_dir=self.asset_dir,
                    output_path=out_path,
                    aspect=self.aspect,
                    seed=self.seed + idx,
                    voice=self.voice,
                    bgm_path=self.bgm_path,
                )
                completed += 1
                results.append(manifest)
                state["completed"] = completed
                state["items"].append({"topic": topic, "status": "completed", "path": str(out_path)})
            except Exception as exc:
                failed += 1
                state["failed"] = failed
                state["items"].append({"topic": topic, "status": "failed", "error": str(exc)})

            self._save_state(state)

        state["running"] = False
        state["finished"] = True
        self._save_state(state)
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
