"""vibevoice synthesis worker — subprocess entry point.

Invoked by hevi.audio.tts_service._run_worker() as a subprocess.
Reads a JSON args-file, delegates to oprim.vibevoice_synthesize, then exits.
On exit the OS fully reclaims all VRAM.

Usage:
    python vibevoice_worker.py <args.json>

Args JSON schema:
    {
      "script": [{"speaker_id": "host", "text": "...", "voice_ref": null}],
      "output_path": "/tmp/out.wav",
      "model_dir": "/home/user/models/vibevoice-1.5b",
      "watermark": false
    }
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _Line:
    speaker_id: str
    text: str
    voice_ref: Path | None = None


async def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))

    script = [
        _Line(
            speaker_id=line["speaker_id"],
            text=line["text"],
            voice_ref=Path(line["voice_ref"]) if line.get("voice_ref") else None,
        )
        for line in data["script"]
    ]

    from oprim import vibevoice_synthesize

    await vibevoice_synthesize(
        config={"VIBEVOICE_MODEL_DIR": data["model_dir"]},
        script=script,
        output_path=Path(data["output_path"]),
        watermark=data.get("watermark", True),
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: vibevoice_worker.py <args.json>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
