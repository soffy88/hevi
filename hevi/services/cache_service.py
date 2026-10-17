"""
Caching service for microservices architecture
"""
import redis.asyncio as aioredis
import json
import pickle
from typing import Any, Optional, Union
from datetime import timedelta
from ..core.config import settings
from .base import BaseService


class CacheService(BaseService):
    """
    Service class for caching operations using Redis
    """
    
    def __init__(self):
        super().__init__()
        self.redis_url = settings.redis_url
        self._redis = None
        
    async def connect(self):
        """Establish connection to Redis"""
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=False)
        return self._redis
    
    async def get(self, key: str) -> Optional[Any]:
        """Get a value from cache"""
        redis_client = await self.connect()
        try:
            value = await redis_client.get(key)
            if value is not None:
                # Try to deserialize as JSON first, then as pickle
                try:
                    return json.loads(value.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return pickle.loads(value)
            return None
        except Exception as e:
            self.logger.warning(f"Cache GET error for key {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[Union[int, timedelta]] = None) -> bool:
        """Set a value in cache with optional TTL"""
        redis_client = await self.connect()
        try:
            # Serialize the value
            if isinstance(value, (dict, list, str, int, float, bool)):
                serialized_value = json.dumps(value).encode('utf-8')
            else:
                serialized_value = pickle.dumps(value)
                
            # Set with TTL if provided
            if ttl is not None:
                await redis_client.setex(key, ttl, serialized_value)
            else:
                await redis_client.set(key, serialized_value)
            return True
        except Exception as e:
            self.logger.warning(f"Cache SET error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete a value from cache"""
        redis_client = await self.connect()
        try:
            result = await redis_client.delete(key)
            return result > 0
        except Exception as e:
            self.logger.warning(f"Cache DELETE error for key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache"""
        redis_client = await self.connect()
        try:
            return await redis_client.exists(key) > 0
        except Exception as e:
            self.logger.warning(f"Cache EXISTS error for key {key}: {e}")
            return False
    
    async def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern"""
        redis_client = await self.connect()
        try:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
            return len(keys)
        except Exception as e:
            self.logger.warning(f"Cache CLEAR_PATTERN error for pattern {pattern}: {e}")
            return 0
    
    async def close(self):
        """Close the Redis connection"""
        if self._redis:
            await self._redis.close()
            await self._redis.connection_pool.disconnect()


# Singleton instance
cache_service = CacheService()