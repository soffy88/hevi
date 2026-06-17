import asyncio
import logging
import signal

from hevi.queue.task_queue import dequeue
from hevi.tasks.task_service import TaskService

logger = logging.getLogger(__name__)

class QueueWorker:
    def __init__(self, task_service: TaskService, poll_interval: float = 5.0):
        self.task_service = task_service
        self.poll_interval = poll_interval
        self._running = False
        self._current_task_id = None

    async def run(self) -> None:
        """Run the worker loop."""
        self._running = True
        logger.info("Queue worker started")
        
        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                # Signal handlers not supported on all platforms (e.g. Windows)
                pass

        while self._running:
            try:
                task = await dequeue(self.task_service.repository)
                if task:
                    task_id = task["id"]
                    self._current_task_id = task_id
                    logger.info(f"Processing task {task_id}")
                    try:
                        await self.task_service.run_task(task_id)
                    except Exception as e:
                        logger.error(f"Error running task {self._current_task_id}: {e}")
                    finally:
                        self._current_task_id = None
                else:
                    await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(self.poll_interval)

        logger.info("Queue worker stopped")

    def stop(self) -> None:
        """Signal the worker to stop."""
        logger.info("Stopping queue worker...")
        self._running = False
