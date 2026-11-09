"""MiniMax-H3 official API provider.

Verified against the official MiniMax docs (2026-11-09):

  POST https://api.minimax.cn/v2/video_generation
    Authorization: Bearer $MINIMAX_API_KEY
    {
      "model": "MiniMax-H3",
      "content": [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "..."},
         "role": "first_frame" | "last_frame" | "reference_image"},
        {"type": "audio_url", "audio_url": {"url": "..."}, "role": "reference_audio"}
      ],
      "duration": 5, "resolution": "768P", "ratio": "9:16"
    }
  GET https://api.minimax.cn/v2/query/video_generation/{task_id}
  -> task.status in processing/succeeded/failed/cancelled; task.content.url on success

The endpoint takes public URLs for media.  This provider does not invent an
upload API: local files are only accepted when ``MINIMAX_FILE_BASE`` maps
this machine's files to public URLs.  Without it, reference modes refuse and
selection falls back to Offline.  Text-to-video has no such requirement.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


from .base import VideoRequest, VideoResult

BASE = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.cn")
CREATE = BASE + "/v2/video_generation"
QUERY = BASE + "/v2/query/video_generation/{task_id}"
MAX_IMAGES = 9
MAX_AUDIO = 3


class MiniMaxConfigError(RuntimeError):
    pass


def _public_url(path: str, base: str) -> str:
    p = Path(path)
    if str(path).startswith(("http://", "https://")):
        return str(path)
    if not base:
        raise MiniMaxConfigError("本地素材需要 MINIMAX_FILE_BASE（公网可访问的文件前缀）")
    return base.rstrip("/") + "/" + p.name


class MiniMaxH3APIProvider:
    name = "minimax_h3_api"

    def __init__(self, *, ledger: Any = None) -> None:
        self.ledger = ledger

    def available(self) -> tuple[bool, str]:
        if not os.environ.get("MINIMAX_API_KEY", "").strip():
            return False, "MINIMAX_API_KEY 未设置"
        return True, "MiniMax-H3 official API key present"

    def _content(self, req: VideoRequest) -> list[dict[str, Any]]:
        base = os.environ.get("MINIMAX_FILE_BASE", "").strip()
        content: list[dict[str, Any]] = [{"type": "text", "text": req.prompt}]
        images = list(req.reference_images)[:MAX_IMAGES]
        if req.mode == "first_last":
            if not req.first_frame or not req.last_frame:
                raise ValueError("first_last 模式需要首帧和尾帧")
            content.extend([
                {"type": "image_url", "image_url": {"url": _public_url(req.first_frame, base)},
                 "role": "first_frame"},
                {"type": "image_url", "image_url": {"url": _public_url(req.last_frame, base)},
                 "role": "last_frame"},
            ])
        elif req.mode in ("reference", "digital_human"):
            content.extend(
                {"type": "image_url", "image_url": {"url": _public_url(path, base)}, "role": "reference_image"}
                for path in images
            )
            content.extend(
                {"type": "audio_url", "audio_url": {"url": _public_url(path, base)}, "role": "reference_audio"}
                for path in list(req.reference_audio)[:MAX_AUDIO]
            )
        return content

    def render(self, req: VideoRequest) -> VideoResult:
        import httpx

        key = os.environ.get("MINIMAX_API_KEY", "").strip()
        if not key:
            raise MiniMaxConfigError("MINIMAX_API_KEY 未设置")
        content = self._content(req)
        duration = round(min(15, max(4, req.duration_s)))
        payload: dict[str, Any] = {
            "model": os.environ.get("MINIMAX_H3_MODEL", "MiniMax-H3"),
            "content": content,
            "duration": duration,
            "resolution": os.environ.get("MINIMAX_H3_RESOLUTION", "768P"),
        }
        if req.mode == "t2v":
            payload["ratio"] = req.aspect
        elif req.mode in ("first_last", "reference", "digital_human"):
            payload["ratio"] = "adaptive"
        price = None
        if self.ledger is not None:
            price = self.ledger.reserve(self.name, duration, ref=req.shot_id)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=180) as client:
            r = client.post(CREATE, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            base_resp = data.get("base_resp") or {}
            if int(base_resp.get("status_code", 0)) != 0:
                if self.ledger is not None:
                    self.ledger.settle(self.name, duration, ref=req.shot_id, success=False,
                                       note=str(base_resp))
                raise RuntimeError(f"MiniMax create failed: {base_resp}")
            task_id = data.get("task_id")
            if not task_id:
                raise RuntimeError(f"MiniMax create returned no task_id: {data}")
            deadline = time.time() + float(os.environ.get("MINIMAX_TIMEOUT_S", "1800"))
            url = ""
            status = ""
            while time.time() < deadline:
                time.sleep(float(os.environ.get("MINIMAX_POLL_S", "10")))
                q = client.get(QUERY.format(task_id=task_id), headers={"Authorization": f"Bearer {key}"})
                q.raise_for_status()
                task = q.json().get("task") or q.json()
                status = str(task.get("status") or "")
                if status == "succeeded":
                    url = str((task.get("content") or {}).get("url") or "")
                    break
                if status in ("failed", "cancelled"):
                    break
            if not url:
                if self.ledger is not None:
                    self.ledger.settle(self.name, duration, ref=req.shot_id, success=False,
                                       note=f"status={status or 'timeout'}")
                raise RuntimeError(f"MiniMax 任务未产出视频（status={status or 'timeout'}）")
            out = Path(req.output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with client.stream("GET", url, timeout=300) as resp:
                resp.raise_for_status()
                with out.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        if self.ledger is not None:
            self.ledger.settle(self.name, duration, ref=req.shot_id, success=True,
                               note=f"task_id={task_id}")
        return VideoResult(out, self.name, duration, {
            "task_id": task_id,
            "remote_url": url,
            "price": price,
            "license_note": "MiniMax H3 community licence excludes EU/UK/KR/US; commercially-facing UI must show 'MiniMax H3'",
        })
