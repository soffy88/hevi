"""omodul:omodul_run_store —— Lite run 状态落盘(重启可恢复)。

目录约定::
    data/lite_runs/{run_id}/
        run.json          # LiteRunRecord 全量 JSON
        preview.html      # 审稿 HTML 预览(不落 MP4)

纯文件 I/O,无 SQLite 依赖 —— 与 tongjian 的 output/tongjian/{run_id} 同哲学。
内存表仍是热缓存; 每次 mutate 后 save; get 未命中时 load。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from hevi.pipeline_lite.schemas import LiteRunRecord

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path("data/lite_runs")


def runs_root() -> Path:
    """可测:环境变量 HEVI_LITE_RUNS_DIR 覆盖根目录。"""
    raw = os.environ.get("HEVI_LITE_RUNS_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_ROOT


def run_dir(run_id: str) -> Path:
    d = runs_root() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_json_path(run_id: str) -> Path:
    return run_dir(run_id) / "run.json"


def preview_html_path(run_id: str) -> Path:
    return run_dir(run_id) / "preview.html"


def save_run(rec: LiteRunRecord) -> Path:
    """原子写 run.json(写 tmp 再 rename)。"""
    path = run_json_path(rec.run_id)
    tmp = path.with_suffix(".json.tmp")
    payload = rec.model_dump(mode="json")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_run(run_id: str) -> LiteRunRecord | None:
    path = run_json_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LiteRunRecord.model_validate(data)
    except Exception as exc:
        logger.warning("lite run %s 落盘损坏,忽略: %s", run_id, exc)
        return None


def list_run_ids(*, limit: int = 50) -> list[str]:
    root = runs_root()
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and (p / "run.json").is_file()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in dirs[: max(1, limit)]]


def delete_run_dir(run_id: str) -> None:
    """测试清理用。"""
    import shutil

    d = runs_root() / run_id
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


__all__ = [
    "delete_run_dir",
    "list_run_ids",
    "load_run",
    "preview_html_path",
    "run_dir",
    "run_json_path",
    "runs_root",
    "save_run",
]
