"""v9.1 基建:公共 WorkspaceManager —— 统一的任务沙盒 + 状态中枢。

两条生产管道共用:
  * 主管道 (Remotion / hevi.explainer)
  * Lite 管道 (HTML + Playwright / hevi.pipeline_lite)

职责:
  1. 为每个工单创建独立沙盒目录 ``data/workspace/{task_id}/``,下设
     ``inputs/``(素材入参)、``assets/``(TTS 音频/录屏等中间产物)、
     ``outputs/``(最终成片)。
  2. 状态不再写散装 state.json —— 全部落到 SQLite ``TaskRun`` 表
     (hevi.core.db),``save_state``/``get_state`` 即增删改查;任何一步崩溃后
     重试都能依据颗粒度状态机跳过已完成步骤,绝不重复消耗算力和 API 额度。
  3. 每次状态/进度变化同步调用 ``ConnectionManager.broadcast_task_update``,
     让前端任务大盘实时跳动(WebSocket 推流)。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from hevi.core.db import engine, init_db
from hevi.core.models import TaskRun
from hevi.core.ws_manager import connection_manager

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ROOT = Path("data/workspace")


def new_task_id() -> str:
    """生成短工单 ID(与 TaskRun.task_id / 沙盒目录同名)。"""
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fire_broadcast(task_id: str, status: str, progress: int) -> None:
    """推流:有事件循环时 fire-and-forget;纯同步上下文(测试/脚本)静默跳过。

    推流失败绝不影响生产任务本身 —— 大盘只是观测面。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop.is_running():
        # RUF006:保留 task 引用,避免被 GC;失败不影响生产路径。
        _broadcast_task = loop.create_task(
            connection_manager.broadcast_task_update(task_id, status, progress)
        )
        _broadcast_task.add_done_callback(lambda _t: None)


class WorkspaceManager:
    """任务沙盒 + 状态中枢。两条管道共用,Session 每次新建,线程安全。"""

    def __init__(
        self,
        task_id: str,
        *,
        pipeline_type: str = "main_remotion",
        workspace_root: Path | str = DEFAULT_WORKSPACE_ROOT,
        register: bool = True,
    ) -> None:
        self.task_id = task_id
        self.pipeline_type = pipeline_type
        self.root = Path(workspace_root) / task_id
        self.inputs = self.root / "inputs"
        self.assets = self.root / "assets"
        self.outputs = self.root / "outputs"
        self._ensure_dirs()
        if register:
            self._register_task()

    # ── 目录沙盒 ──────────────────────────────────────────────
    def _ensure_dirs(self) -> None:
        for directory in (self.inputs, self.assets, self.outputs):
            directory.mkdir(parents=True, exist_ok=True)

    def put_input(self, name: str, content: bytes | str) -> Path:
        """写入 inputs/ 并返回路径(bytes 原样写;str 按 utf-8 写)。"""
        target = self.inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        return target

    def asset_path(self, name: str) -> Path:
        return self.assets / name

    def output_path(self, name: str) -> Path:
        return self.outputs / name

    # ── DB 状态机 ─────────────────────────────────────────────
    def _register_task(self) -> None:
        """工单首次出现时落一行 pending;已存在则只刷新 pipeline_type。"""
        init_db()
        with Session(engine) as session:
            existing = session.exec(
                select(TaskRun).where(TaskRun.task_id == self.task_id)
            ).first()
            if existing is None:
                session.add(
                    TaskRun(
                        task_id=self.task_id,
                        pipeline_type=self.pipeline_type,
                        status="pending",
                        progress=0,
                        state_json={},
                    )
                )
                session.commit()
            elif existing.pipeline_type != self.pipeline_type:
                existing.pipeline_type = self.pipeline_type
                session.commit()

    def _row(self, session: Session) -> TaskRun | None:
        return session.exec(select(TaskRun).where(TaskRun.task_id == self.task_id)).first()

    def save_state(self, key: str, value: Any, *, broadcast: bool = True) -> None:
        """颗粒度状态机写入:state_json[key] = value;再推流顶层 status/progress。

        key 约定:顶层字段用 ``status``/``progress``/``error``,步骤级用
        ``<step>_status``(如 ``tts_status``/``asr_status``/``render_status``)。
        """
        with Session(engine) as session:
            row = self._row(session)
            if row is None:
                row = TaskRun(task_id=self.task_id, pipeline_type=self.pipeline_type)
                session.add(row)
                session.flush()
            state = dict(row.state_json or {})
            state[key] = value
            row.state_json = state
            row.updated_at = _utcnow()
            if key == "status":
                row.status = str(value)
            elif key == "progress":
                row.progress = int(value)
            elif key == "error":
                row.error_log = str(value)[:4000]
            session.commit()
            status = row.status
            progress = row.progress
        if broadcast:
            _fire_broadcast(self.task_id, status, progress)

    def get_state(self, key: str) -> Any:
        """读颗粒度状态;未写入返回 None。"""
        with Session(engine) as session:
            row = self._row(session)
            if row is None:
                return None
            state = dict(row.state_json or {})
            if key in ("status", "progress", "error"):
                return {
                    "status": row.status,
                    "progress": row.progress,
                    "error": row.error_log,
                }.get(key)
            return state.get(key)

    def record_result_sha(self, output_path: Path | str) -> str | None:
        """v9.1 产物 SHA-256 身份绑定: 返工后审核永远对着同一稿。

        计算最终成片的 SHA-256 并写入 state_json[result_sha](与
        result_video_path 配套)。文件缺失返回 None(不抛错)。
        """
        import hashlib

        path = Path(output_path)
        if not path.exists() or path.stat().st_size == 0:
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save_state("result_sha", digest)
        return digest

    def snapshot(self) -> dict[str, Any]:
        """整行快照(大盘/断点续传用)。"""
        with Session(engine) as session:
            row = self._row(session)
            if row is None:
                return {}
            return {
                "task_id": row.task_id,
                "pipeline_type": row.pipeline_type,
                "status": row.status,
                "progress": row.progress,
                "error_log": row.error_log,
                "state_json": dict(row.state_json or {}),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    # ── 一步一更新:断点续传核心 ─────────────────────────────
    def mark_step_done(self, step: str, progress: int | None = None) -> None:
        """步骤完成:state_json[<step>_status] = "done";可选同步推进顶层进度。"""
        key = f"{step}_status"
        self.save_state(key, "done")
        if progress is not None:
            self.save_state("progress", progress)

    def is_step_done(self, step: str) -> bool:
        """步骤已完成?重试时据此跳过,绝不重复消耗算力/API 额度。"""
        return bool(self.get_state(f"{step}_status") == "done")

    def update_progress(self, status: str, progress: int, *, error: str | None = None) -> None:
        """顶层流转:status + progress 一并写库并推流。"""
        self.save_state("status", status)
        self.save_state("progress", progress)
        if error:
            self.save_state("error", error)

    def mark_failed(self, error: str) -> None:
        self.save_state("status", "failed")
        self.save_state("error", error)


__all__ = ["DEFAULT_WORKSPACE_ROOT", "WorkspaceManager", "new_task_id"]
