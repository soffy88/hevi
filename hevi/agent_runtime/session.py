"""
会话索引（对标 ViMax session_index.py）

管理长任务的会话持久化：
- 创建/激活/列出会话
- 存储 turn records（用户输入 + 模型输出 + 工具调用）
- 支持 resume 中断的会话
- 压缩记录管理
"""
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime


@dataclass
class TurnRecord:
    """单次对话轮次记录"""
    turn_id: str
    user_input: str
    assistant_output: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TurnRecord":
        return cls(**data)


@dataclass
class CompactionRecord:
    """上下文压缩记录"""
    compaction_id: str
    timestamp: float
    messages_before: int
    messages_after: int
    tokens_before: int
    tokens_after: int
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionRecord":
        return cls(**data)


@dataclass
class SessionMetadata:
    """会话元数据"""
    session_id: str
    created_at: float
    updated_at: float
    turn_count: int = 0
    total_tokens: int = 0
    status: str = "active"  # active | paused | completed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMetadata":
        return cls(**data)


class SessionIndex:
    """
    会话索引管理器

    目录结构:
    sessions/
    ├── active.json          # 当前活跃会话 ID
    ├── {session_id}/
    │   ├── metadata.json    # 会话元数据
    │   ├── turns/
    │   │   ├── turn_001.json
    │   │   ├── turn_002.json
    │   │   └── ...
    │   └── compactions/
    │       ├── compaction_001.json
    │       └── ...
    """

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.active_file = self.sessions_dir / "active.json"

    def create_session(self, session_id: Optional[str] = None) -> str:
        """创建新会话"""
        if session_id is None:
            session_id = str(uuid.uuid4())

        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "turns").mkdir(exist_ok=True)
        (session_dir / "compactions").mkdir(exist_ok=True)

        metadata = SessionMetadata(
            session_id=session_id,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._save_metadata(session_id, metadata)

        # 设为活跃会话
        self.set_active(session_id)

        return session_id

    def get_session(self, session_id: str) -> Optional[SessionMetadata]:
        """获取会话元数据"""
        metadata_file = self.sessions_dir / session_id / "metadata.json"
        if not metadata_file.exists():
            return None
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return SessionMetadata.from_dict(json.load(f))

    def list_sessions(self, limit: int = 50) -> List[SessionMetadata]:
        """列出所有会话"""
        sessions = []
        for session_dir in self.sessions_dir.iterdir():
            if session_dir.is_dir() and session_dir.name != ".git":
                metadata = self.get_session(session_dir.name)
                if metadata:
                    sessions.append(metadata)

        # 按更新时间排序
        sessions.sort(key=lambda m: m.updated_at, reverse=True)
        return sessions[:limit]

    def get_active(self) -> Optional[str]:
        """获取当前活跃会话 ID"""
        if not self.active_file.exists():
            return None
        with open(self.active_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("session_id")

    def set_active(self, session_id: str) -> None:
        """设置活跃会话"""
        with open(self.active_file, 'w', encoding='utf-8') as f:
            json.dump({"session_id": session_id}, f)

    def add_turn(self, session_id: str, turn: TurnRecord) -> None:
        """添加对话轮次"""
        session_dir = self.sessions_dir / session_id
        turns_dir = session_dir / "turns"
        turns_dir.mkdir(parents=True, exist_ok=True)

        # 生成序号文件名
        existing = list(turns_dir.glob("turn_*.json"))
        turn_num = len(existing) + 1
        turn_file = turns_dir / f"turn_{turn_num:03d}.json"

        with open(turn_file, 'w', encoding='utf-8') as f:
            json.dump(turn.to_dict(), f, ensure_ascii=False, indent=2)

        # 更新元数据
        metadata = self.get_session(session_id)
        if metadata:
            metadata.turn_count += 1
            metadata.updated_at = time.time()
            self._save_metadata(session_id, metadata)

    def get_turns(self, session_id: str) -> List[TurnRecord]:
        """获取所有对话轮次"""
        turns_dir = self.sessions_dir / session_id / "turns"
        if not turns_dir.exists():
            return []

        turns = []
        for turn_file in sorted(turns_dir.glob("turn_*.json")):
            with open(turn_file, 'r', encoding='utf-8') as f:
                turns.append(TurnRecord.from_dict(json.load(f)))
        return turns

    def add_compaction(self, session_id: str, compaction: CompactionRecord) -> None:
        """添加压缩记录"""
        session_dir = self.sessions_dir / session_id
        compactions_dir = session_dir / "compactions"
        compactions_dir.mkdir(parents=True, exist_ok=True)

        existing = list(compactions_dir.glob("compaction_*.json"))
        comp_num = len(existing) + 1
        comp_file = compactions_dir / f"compaction_{comp_num:03d}.json"

        with open(comp_file, 'w', encoding='utf-8') as f:
            json.dump(compaction.to_dict(), f, ensure_ascii=False, indent=2)

    def get_compactions(self, session_id: str) -> List[CompactionRecord]:
        """获取所有压缩记录"""
        compactions_dir = self.sessions_dir / session_id / "compactions"
        if not compactions_dir.exists():
            return []

        compactions = []
        for comp_file in sorted(compactions_dir.glob("compaction_*.json")):
            with open(comp_file, 'r', encoding='utf-8') as f:
                compactions.append(CompactionRecord.from_dict(json.load(f)))
        return compactions

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        import shutil
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            return False

        shutil.rmtree(session_dir)

        # 如果删除的是活跃会话，清除活跃标记
        if self.get_active() == session_id:
            if self.active_file.exists():
                self.active_file.unlink()

        return True

    def _save_metadata(self, session_id: str, metadata: SessionMetadata) -> None:
        """保存会话元数据"""
        metadata_file = self.sessions_dir / session_id / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)

    def resume_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """恢复会话，返回上下文"""
        metadata = self.get_session(session_id)
        if not metadata:
            return None

        self.set_active(session_id)

        turns = self.get_turns(session_id)
        compactions = self.get_compactions(session_id)

        return {
            "metadata": metadata,
            "turns": turns,
            "compactions": compactions,
        }
