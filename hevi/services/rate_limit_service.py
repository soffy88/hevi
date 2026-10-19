"""
Rate Limiting service for microservices architecture
"""
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis

from ..core.config import settings
from .base import BaseService


class RateLimitService(BaseService):
    """
    Service class for handling API rate limiting using Redis
    """
    
    def __init__(self) -> None:
        super().__init__()
        self.redis_url = settings.redis_url
        self._redis: Any = None
        
    async def connect(self) -> Any:
        """Establish connection to Redis"""
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis
    
    async def is_rate_limited(
        self, 
        key: str, 
        max_requests: int, 
        window_seconds: int,
        increment: bool = True
    ) -> tuple[bool, int, int]:
        """
        Check if a key is rate limited.
        
        Returns:
            tuple[bool, int, int]: (is_limited, current_count, reset_time_seconds)
        """
        redis_client = await self.connect()
        
        # Create a timestamp-based window key
        window_key = f"rate_limit:{key}:{window_seconds}"
        
        # Use Redis time to ensure consistency across instances
        current_time = datetime.now()
        window_start = int(current_time.timestamp()) // window_seconds
        window_reset_time = (window_start + 1) * window_seconds
        
        # Create a key that resets based on the window
        reset_key = f"{window_key}:{window_start}"
        
        try:
            if increment:
                # Increment the count and set expiration
                pipe = redis_client.pipeline()
                pipe.incr(reset_key)
                pipe.expire(reset_key, window_seconds)
                results = await pipe.execute()
                current_count = results[0]
            else:
                # Just get the current count
                current_count = await redis_client.get(reset_key)
                current_count = int(current_count) if current_count else 0
            
            is_limited = current_count > max_requests
            time_remaining = window_reset_time - int(current_time.timestamp())
            
            return is_limited, current_count, max(time_remaining, 0)
            
        except Exception as e:
            self.logger.warning(f"Rate limiting error for key {key}: {e}")
            # If Redis fails, allow the request to go through
            return False, 0, 0
    
    async def get_rate_limit_info(
        self, 
        key: str, 
        max_requests: int, 
        window_seconds: int
    ) -> dict[str, int | bool]:
        """
        Get rate limit information without incrementing the counter
        """
        is_limited, current_count, time_remaining = await self.is_rate_limited(
            key, max_requests, window_seconds, increment=False
        )
        
        return {
            "limit": max_requests,
            "remaining": max(max_requests - current_count, 0),
            "reset": time_remaining,
            "is_limited": is_limited
        }
    
    async def apply_rate_limit(
        self, 
        key: str, 
        max_requests: int, 
        window_seconds: int
    ) -> bool:
        """
        Apply rate limiting and return whether the request should be allowed
        """
        is_limited, _, _ = await self.is_rate_limited(key, max_requests, window_seconds)
        return not is_limited


# Singleton instance
rate_limit_service = RateLimitService()