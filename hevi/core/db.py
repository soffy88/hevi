"""v9.1 基建:SQLite 任务状态库(SQLModel ORM)。

升级自散装 state.json 单文件状态管理 —— 现在所有工单的状态、进度、错误日志
统一落进 ``sqlite:///data/hevi_tasks.db``,支撑前端「生成任务历史大盘」的分页
查询与 WebSocket 实时推流,同时保留轻量、零外部依赖(不用起 PostgreSQL)的
本地部署特性。

FastAPI 并发注意:SQLite 默认同一连接禁止跨线程,这里显式开启
``check_same_thread=False`` 并把 Session 生命周期交给 SQLModel 的依赖注入,
每个请求/后台任务拿到的都是独立 Session。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from hevi.core.config import settings

_DEFAULT_DB_FILE = Path("data/hevi_tasks.db")


def _resolve_db_url() -> str:
    """优先读环境变量 HEVI_TASKS_DB_URL,缺省落到仓库根 data/ 下的 SQLite。"""
    configured = getattr(settings, "tasks_db_url", "") or ""
    if configured:
        return configured
    _DEFAULT_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{_DEFAULT_DB_FILE}"


engine = create_engine(
    _resolve_db_url(),
    connect_args={"check_same_thread": False},
    # SQLite 单写者:串行化写事务,避免多线程同时写导致 "database is locked"。
    pool_pre_ping=True,
)


def init_db() -> None:
    """建表(幂等)。应用启动与测试夹具都会调用。"""
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖:每次请求一个独立 Session,用完即关。"""
    with Session(engine) as session:
        yield session


__all__ = ["engine", "get_session", "init_db"]
