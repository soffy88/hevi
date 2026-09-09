"""Native Duix HTTP adapter used by the canonical HEVI container.

The upstream Duix extension exposes ``TransDhTask(code, ...)`` and ``work()``
but the old HEVI-facing app expected a singleton ``instance()`` API and passed
still images as ``video_url``. This module supplies only that compatibility:
the upstream extension remains loaded, and every task delegates to its native
``work()`` implementation.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

import service.trans_dh_service as _native
from flask import Flask, jsonify, request

LOGGER = logging.getLogger("hevi.duix.native")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATA_ROOT = Path("/code/data")
TEMP_ROOT = DATA_ROOT / "temp"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

app = Flask(__name__)
task_dic = _native.task_dic
Status = _native.Status
NativeTransDhTask = _native.TransDhTask

_active_lock = threading.Lock()
_active = False
_runtime_ready = False
_singleton: TransDhTask | None = None


def _response(code: int, success: bool, msg: str, data: dict[str, Any]) -> str:
    return json.dumps(
        {"code": code, "success": success, "msg": msg, "data": data},
        ensure_ascii=False,
    )


def _duration_seconds(audio_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError("音频时长必须大于 0")
    return duration


def _normalize_presenter(video_url: str, code: str, audio_path: Path) -> str:
    """Return a native-compatible video, deriving one from a still image."""

    presenter = Path(video_url)
    if not presenter.is_file():
        raise FileNotFoundError(f"presenter 不存在: {presenter}")
    if presenter.suffix.lower() not in IMAGE_SUFFIXES:
        return str(presenter)

    task_dir = TEMP_ROOT / code
    task_dir.mkdir(parents=True, exist_ok=True)
    derived = task_dir / "presenter_reference.mp4"
    duration = _duration_seconds(audio_path)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            str(presenter),
            "-t",
            f"{duration:.6f}",
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-r",
            "25",
            "-an",
            str(derived),
        ],
        check=True,
        capture_output=True,
    )
    if not derived.is_file() or derived.stat().st_size == 0:
        raise RuntimeError(f"presenter video 生成失败: {derived}")
    return str(derived)


class TransDhTask:
    """Compatibility facade whose work method is the native work method."""

    def __init__(
        self,
        code: str,
        audio_url: str,
        video_url: str,
        watermark_switch: int,
        digital_auth: int,
        chaofen: int,
        pn: int,
    ) -> None:
        self._native_task = NativeTransDhTask(
            code,
            audio_url,
            video_url,
            watermark_switch,
            digital_auth,
            chaofen,
            pn,
        )

    @classmethod
    def instance(cls) -> TransDhTask:
        """Provide the legacy singleton hook without replacing native work."""

        global _singleton
        if _singleton is None:
            _singleton = object.__new__(cls)
            _singleton._native_task = None  # type: ignore[attr-defined]
        return _singleton

    @property
    def run_flag(self) -> bool:
        with _active_lock:
            return _active

    @run_flag.setter
    def run_flag(self, value: bool) -> None:
        del value

    @property
    def run_lock(self) -> threading.Lock:
        return _active_lock

    @property
    def task_dic(self) -> dict[str, Any]:
        return task_dic

    def work(self) -> Any:
        if self._native_task is None:
            raise RuntimeError("TransDhTask.instance() 不能直接执行未参数化任务")
        return self._native_task.work()

    def change_task_status(self, *args: Any) -> Any:
        if self._native_task is None:
            raise RuntimeError("native task 未初始化")
        return self._native_task.change_task_status(*args)


# Keep imports that expect service.trans_dh_service.TransDhTask working while
# retaining the actual extension class in NativeTransDhTask.
_native.TransDhTask = TransDhTask


def _run_native(task: TransDhTask, code: str) -> None:
    global _active
    try:
        task.work()
    except Exception as exc:  # pragma: no cover - native-only failure path
        LOGGER.exception("Duix native task failed: %s", code)
        try:
            task.change_task_status(code, Status.error, 0, "", str(exc))
        except Exception:
            LOGGER.exception("Duix native task status update failed: %s", code)
    finally:
        with _active_lock:
            _active = False


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "healthy", "native": _runtime_ready})


@app.post("/easy/submit")
def submit() -> str:
    global _active
    try:
        payload = request.get_json(force=True) or {}
        audio_url = str(payload.get("audio_url") or "")
        video_url = str(payload.get("video_url") or "")
        code = str(payload.get("code") or "")
        if not audio_url or not video_url or not code or not CODE_RE.fullmatch(code):
            return _response(10002, False, "参数异常", {})
        audio_path = Path(audio_url)
        if not audio_path.is_file():
            return _response(10002, False, f"audio 不存在: {audio_path}", {})

        with _active_lock:
            if _active:
                return _response(10001, True, "忙碌中", {})
            _active = True

        native_video = _normalize_presenter(video_url, code, audio_path)
        task = TransDhTask(
            code,
            str(audio_path),
            native_video,
            int(payload.get("watermark_switch") or 0),
            int(payload.get("digital_auth") or 0),
            int(payload.get("chaofen") or 0),
            int(payload.get("pn") or 0),
        )
        task_dic[code] = (Status.run, 0, "", "")
        threading.Thread(target=_run_native, args=(task, code), daemon=True).start()
        return _response(10000, True, "已提交 native inference", {})
    except Exception as exc:
        with _active_lock:
            _active = False
        LOGGER.exception("Duix native submit failed")
        return _response(9999, False, str(exc), {})


@app.get("/easy/query")
def query() -> str:
    code = str(request.args.get("code") or "")
    if not code:
        return _response(10002, False, "code 参数缺失", {})
    entry = task_dic.get(code)
    if entry is None:
        return _response(10003, True, "任务不存在", {})
    status, progress, result, msg, *extra = entry
    data: dict[str, Any] = {
        "code": code,
        "status": status.value,
        "progress": progress,
        "result": result,
        "msg": msg,
    }
    if status == Status.success:
        data.update(
            {
                "cost": extra[0] if len(extra) > 0 else {},
                "video_duration": extra[1] if len(extra) > 1 else 0,
                "width": extra[2] if len(extra) > 2 else 0,
                "height": extra[3] if len(extra) > 3 else 0,
            }
        )
    return _response(10000, True, "", data)


def _initialize_native() -> None:
    global _runtime_ready
    _native.a()
    _native.init_p()
    _runtime_ready = True
    LOGGER.info(
        "Duix native ready: trans_dh=%s ai_service=%s dinet=%s",
        Path(_native.__file__).name,
        Path("/code/service/ai_service.cpython-38-x86_64-linux-gnu.so").is_file(),
        Path("/code/landmark2face_wy/checkpoints/anylang/dinet_v1_20240131.pth").is_file(),
    )


if __name__ == "__main__":
    _initialize_native()
    app.run(host="0.0.0.0", port=8383, debug=False, threaded=False)
