"""RunningHub OpenAPI provider for a MiniMax-H3 ComfyUI workflow.

Verified against the public RunningHub API docs (2026-11-09):
  * task flow: submit -> taskId -> query status -> query outputs
  * POST https://www.runninghub.cn/task/openapi/create
        {apiKey, workflowId, nodeInfoList:[{nodeId, fieldName, fieldValue}]}
  * POST https://www.runninghub.cn/task/openapi/outputs {apiKey, taskId}
  * POST https://www.runninghub.cn/task/openapi/upload (multipart; apiKey, fileType=input, file)
  * status: QUEUED / RUNNING / SUCCESS / FAILED

The public docs do NOT document the node ids/field names of a particular H3
workflow, so this provider refuses to invent them: it requires
``RUNNINGHUB_WORKFLOW_ID`` and ``RUNNINGHUB_NODE_MAP`` (JSON) describing the
role -> node mapping.  Missing either one makes the provider unavailable and
selection falls back to Offline.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


from .base import VideoRequest, VideoResult

API = os.environ.get("RUNNINGHUB_API_BASE", "https://www.runninghub.cn")
CREATE = API + "/task/openapi/create"
OUTPUTS = API + "/task/openapi/outputs"
STATUS = API + "/task/openapi/status"
UPLOAD = API + "/task/openapi/upload"
MAX_IMAGES = 9
MAX_AUDIO = 3
ROLES = {"prompt", "seed", "resolution", "ratio", "mode"} | {f"image{i}" for i in range(1, MAX_IMAGES + 1)} | {
    f"audio{i}" for i in range(1, MAX_AUDIO + 1)
}


class RunningHubConfigError(RuntimeError):
    pass


class RunningHubH3Provider:
    name = "runninghub_h3"

    def __init__(self, *, ledger: Any = None) -> None:
        self.ledger = ledger

    def _config(self) -> tuple[str, str, list[dict[str, Any]]]:
        key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
        workflow = os.environ.get("RUNNINGHUB_WORKFLOW_ID", "").strip()
        raw_map = os.environ.get("RUNNINGHUB_NODE_MAP", "").strip()
        if not key:
            raise RunningHubConfigError("RUNNINGHUB_API_KEY 未设置")
        if not workflow:
            raise RunningHubConfigError("RUNNINGHUB_WORKFLOW_ID 未设置（H3 工作流 ID）")
        if not raw_map:
            raise RunningHubConfigError("RUNNINGHUB_NODE_MAP 未设置（角色->节点字段 JSON）")
        try:
            mapping = json.loads(raw_map)
        except json.JSONDecodeError as exc:
            raise RunningHubConfigError(f"RUNNINGHUB_NODE_MAP 不是合法 JSON: {exc}") from exc
        if not isinstance(mapping, list) or not mapping:
            raise RunningHubConfigError("RUNNINGHUB_NODE_MAP 必须是非空数组")
        for row in mapping:
            if not (row.get("nodeId") and row.get("fieldName") and row.get("role")):
                raise RunningHubConfigError("每个映射项必须含 nodeId/fieldName/role")
            if row["role"] not in ROLES:
                raise RunningHubConfigError(f"未知 role: {row['role']}")
        return key, workflow, mapping

    def available(self) -> tuple[bool, str]:
        try:
            self._config()
            return True, "RunningHub H3 workflow configured"
        except RunningHubConfigError as exc:
            return False, str(exc)

    def _upload(self, key: str, path: Path, client: httpx.Client) -> str:
        with path.open("rb") as fh:
            r = client.post(
                UPLOAD,
                data={"apiKey": key, "fileType": "input"},
                files={"file": (path.name, fh, "application/octet-stream")},
                timeout=120,
            )
        r.raise_for_status()
        data = r.json()
        if data.get("code") not in (0, "0", None):
            raise RuntimeError(f"RunningHub upload failed: {data}")
        payload = data.get("data") or {}
        name = payload.get("fileName") or payload.get("file_name") or payload.get("name")
        if not name:
            raise RuntimeError(f"RunningHub upload returned no file name: {data}")
        return str(name)

    def render(self, req: VideoRequest) -> VideoResult:
        import httpx

        key, workflow, mapping = self._config()
        images = list(req.reference_images)[:MAX_IMAGES]
        audios = list(req.reference_audio)[:MAX_AUDIO]
        if req.mode == "first_last":
            if not req.first_frame or not req.last_frame:
                raise ValueError("first_last 模式需要首帧和尾帧")
            images = [req.first_frame, req.last_frame, *images]
        if req.mode == "digital_human" and not req.reference_audio:
            raise ValueError("digital_human 模式需要音频参考")
        price = None
        if self.ledger is not None:
            price = self.ledger.reserve(self.name, req.duration_s, ref=req.shot_id)

        with httpx.Client(timeout=120) as client:
            uploaded_images = [self._upload(key, Path(p), client) for p in images[:MAX_IMAGES]]
            uploaded_audio = [self._upload(key, Path(p), client) for p in audios]
            values: dict[str, Any] = {
                "prompt": req.prompt,
                "seed": req.seed,
                "resolution": os.environ.get("RUNNINGHUB_RESOLUTION", "640P"),
                "ratio": req.aspect,
                "mode": req.mode,
            }
            for i, name in enumerate(uploaded_images, start=1):
                values[f"image{i}"] = name
            for i, name in enumerate(uploaded_audio, start=1):
                values[f"audio{i}"] = name
            node_info = [
                {"nodeId": row["nodeId"], "fieldName": row["fieldName"], "fieldValue": values[row["role"]]}
                for row in mapping
                if row["role"] in values
            ]
            body = {"apiKey": key, "workflowId": workflow, "nodeInfoList": node_info}
            r = client.post(CREATE, json=body)
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0", None):
                if self.ledger is not None:
                    self.ledger.settle(self.name, req.duration_s, ref=req.shot_id, success=False,
                                       note=f"create failed: {data}")
                raise RuntimeError(f"RunningHub create failed: {data}")
            task_id = (data.get("data") or {}).get("taskId")
            if not task_id:
                raise RuntimeError(f"RunningHub create returned no taskId: {data}")

            deadline = time.time() + float(os.environ.get("RUNNINGHUB_TIMEOUT_S", "1800"))
            url = ""
            last = ""
            while time.time() < deadline:
                time.sleep(float(os.environ.get("RUNNINGHUB_POLL_S", "8")))
                sr = client.post(STATUS, json={"apiKey": key, "taskId": task_id})
                sr.raise_for_status()
                sd = sr.json().get("data") or {}
                last = str(sd.get("taskStatus") or sd.get("status") or "")
                if last.upper() == "SUCCESS":
                    orr = client.post(OUTPUTS, json={"apiKey": key, "taskId": task_id})
                    orr.raise_for_status()
                    od = orr.json()
                    rows = od.get("data") or []
                    if isinstance(rows, dict):
                        rows = rows.get("outputs") or rows.get("files") or [rows]
                    for row in rows:
                        candidate = row.get("fileUrl") or row.get("url") or row.get("file_url")
                        if candidate and str(candidate).lower().endswith((".mp4", ".webm", ".mov")):
                            url = str(candidate)
                            break
                    break
                if last.upper() == "FAILED":
                    break
            if not url:
                if self.ledger is not None:
                    self.ledger.settle(self.name, req.duration_s, ref=req.shot_id, success=False,
                                       note=f"status={last or 'timeout'}")
                raise RuntimeError(f"RunningHub 任务未产出视频（status={last or 'timeout'}）")
            out = Path(req.output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with client.stream("GET", url, timeout=300) as resp:
                resp.raise_for_status()
                with out.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        if self.ledger is not None:
            self.ledger.settle(self.name, req.duration_s, ref=req.shot_id, success=True,
                               note=f"taskId={task_id}")
        return VideoResult(out, self.name, req.duration_s, {
            "task_id": task_id,
            "remote_url": url,
            "price": price,
            "license_note": "MiniMax H3 community licence excludes EU/UK/KR/US; commercially-facing UI must show 'MiniMax H3'",
        })
