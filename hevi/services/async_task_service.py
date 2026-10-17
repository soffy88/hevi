"""
Async Task Management service for microservices architecture
"""
from typing import Any, Callable, Dict, Optional, Awaitable
import asyncio
from datetime import datetime
from .base import BaseService
from .task_service import task_service


class AsyncTaskService(BaseService):
    """
    Service class for managing asynchronous tasks across microservices
    """
    
    def __init__(self):
        super().__init__()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        
    async def execute_with_timeout(
        self, 
        coro: Awaitable[Any], 
        timeout: float,
        task_name: str = "unnamed"
    ) -> Optional[Any]:
        """
        Execute a coroutine with a timeout
        """
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.logger.warning(f"Task {task_name} timed out after {timeout}s")
            return None
        except Exception as e:
            self.logger.error(f"Task {task_name} failed: {e}")
            return None
    
    async def run_background_task(
        self,
        task_func: Callable,
        *args,
        task_id: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Run a function as a background task
        """
        task_id = task_id or f"bg_task_{datetime.now().timestamp()}"
        
        async def wrapped_task():
            try:
                result = await task_func(*args, **kwargs)
                self.logger.info(f"Background task {task_id} completed successfully")
                return result
            except Exception as e:
                self.logger.error(f"Background task {task_id} failed: {e}")
                raise
        
        # Create and store the task
        task = asyncio.create_task(wrapped_task())
        self.active_tasks[task_id] = task
        
        # Clean up completed tasks
        self.active_tasks = {
            tid: t for tid, t in self.active_tasks.items() 
            if not t.done()
        }
        
        return task_id
    
    async def wait_for_task_completion(self, task_id: str, timeout: float = 30.0) -> Optional[Any]:
        """
        Wait for a background task to complete
        """
        if task_id not in self.active_tasks:
            return None
            
        task = self.active_tasks[task_id]
        
        try:
            result = await asyncio.wait_for(task, timeout=timeout)
            # Clean up the completed task
            del self.active_tasks[task_id]
            return result
        except asyncio.TimeoutError:
            self.logger.warning(f"Waiting for task {task_id} timed out")
            return None
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running background task
        """
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            if not task.done():
                task.cancel()
                del self.active_tasks[task_id]
                self.logger.info(f"Task {task_id} was cancelled")
                return True
        return False
    
    async def run_with_retry(
        self,
        func: Callable,
        max_retries: int = 3,
        delay: float = 1.0,
        backoff_factor: float = 2.0,
        *args,
        **kwargs
    ) -> Optional[Any]:
        """
        Run a function with retry logic
        """
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = delay * (backoff_factor ** attempt)
                    self.logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"All {max_retries + 1} attempts failed: {e}")
        
        raise last_exception
    
    def get_active_task_count(self) -> int:
        """
        Get the number of currently active tasks
        """
        # Clean up completed tasks first
        self.active_tasks = {
            tid: t for tid, t in self.active_tasks.items() 
            if not t.done()
        }
        return len(self.active_tasks)


# Singleton instance
async_task_service = AsyncTaskService()