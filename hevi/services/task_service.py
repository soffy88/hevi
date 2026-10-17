"""
Task service implementation for microservices architecture
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from sqlalchemy import select, update, and_
from uuid import UUID

from .base import BaseService
from ..tasks.models import VideoTask as TaskModel
from enum import Enum

class TaskStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CLAIMED = "claimed"


class TaskService(BaseService):
    """
    Service class for task-related operations
    """
    
    async def create_task(self, user_id: str, topic: str, config: Dict[str, Any], 
                         duration_archetype: str = "standard", video_provider: str = "default", 
                         audio_provider: str = "default") -> Optional[dict]:
        """Create a new task"""
        async with self.get_db_session() as session:
            task = TaskModel(
                topic=topic,
                user_id=user_id,
                duration_archetype=duration_archetype,
                video_provider=video_provider,
                audio_provider=audio_provider,
                status=TaskStatus.PENDING.value,
                config_json=config,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(task)
            await session.flush()  # Get the task ID
            
            return {
                "id": str(task.id),
                "user_id": task.user_id,
                "topic": task.topic,
                "status": task.status,
                "config": task.config_json,
                "duration_archetype": task.duration_archetype,
                "video_provider": task.video_provider,
                "audio_provider": task.audio_provider,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None
            }
    
    async def get_task_by_id(self, task_id: str) -> Optional[dict]:
        """Retrieve task by ID"""
        async with self.get_db_session() as session:
            from uuid import UUID
            uuid_task_id = UUID(task_id)
            task = await session.execute(
                select(TaskModel).where(TaskModel.id == uuid_task_id)
            )
            task = task.scalar_one_or_none()
            
            if not task:
                return None
                
            return {
                "id": str(task.id),
                "user_id": task.user_id,
                "topic": task.topic,
                "status": task.status,
                "config": task.config_json,
                "progress": task.progress_pct,
                "result_video_path": task.result_video_path,
                "error": task.error,
                "duration_archetype": task.duration_archetype,
                "video_provider": task.video_provider,
                "audio_provider": task.audio_provider,
                "total_shots": task.total_shots,
                "completed_shots": task.completed_shots,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None
            }
    
    async def update_task_status(self, task_id: str, status: str, progress: Optional[float] = None, 
                                result_video_path: Optional[str] = None, error: Optional[str] = None,
                                total_shots: Optional[int] = None, completed_shots: Optional[int] = None) -> bool:
        """Update task status and related fields"""
        async with self.get_db_session() as session:
            from uuid import UUID
            updates = {
                "status": status,
                "updated_at": datetime.utcnow()
            }
            
            if progress is not None:
                updates["progress_pct"] = progress
            if result_video_path is not None:
                updates["result_video_path"] = result_video_path
            if error is not None:
                updates["error"] = error
            if total_shots is not None:
                updates["total_shots"] = total_shots
            if completed_shots is not None:
                updates["completed_shots"] = completed_shots
            
            stmt = (
                update(TaskModel)
                .where(TaskModel.id == UUID(task_id))
                .values(**updates)
            )
            
            result = await session.execute(stmt)
            return result.rowcount > 0
    
    async def get_user_tasks(self, user_id: str, limit: int = 20, offset: int = 0) -> List[dict]:
        """Get tasks for a specific user"""
        async with self.get_db_session() as session:
            stmt = (
                select(TaskModel)
                .where(TaskModel.user_id == user_id)
                .order_by(TaskModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            
            result = await session.execute(stmt)
            tasks = result.scalars().all()
            
            return [
                {
                    "id": str(task.id),
                    "user_id": task.user_id,
                    "topic": task.topic,
                    "status": task.status,
                    "progress": task.progress_pct,
                    "duration_archetype": task.duration_archetype,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None
                }
                for task in tasks
            ]
    
    async def get_tasks_by_status(self, status: str, limit: int = 20) -> List[dict]:
        """Get tasks by status"""
        async with self.get_db_session() as session:
            stmt = (
                select(TaskModel)
                .where(TaskModel.status == status)
                .order_by(TaskModel.created_at.asc())
                .limit(limit)
            )
            
            result = await session.execute(stmt)
            tasks = result.scalars().all()
            
            return [
                {
                    "id": str(task.id),
                    "user_id": task.user_id,
                    "topic": task.topic,
                    "status": task.status,
                    "duration_archetype": task.duration_archetype,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None
                }
                for task in tasks
            ]


# Singleton instance
task_service = TaskService()