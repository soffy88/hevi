"""
Base service class defining common patterns for all microservices
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging
from contextlib import asynccontextmanager
from ..db.pg_pool import get_hevi_pg_pool
from ..db.database import AsyncSessionLocal


class BaseService(ABC):
    """
    Abstract base class for all services providing common functionality
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        
    @asynccontextmanager
    async def get_db_session(self):
        """Context manager for database sessions"""
        async with AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
                
    @asynccontextmanager
    async def get_db_connection(self):
        """Context manager for direct database connections"""
        pool = await get_hevi_pg_pool()
        async with pool.acquire() as conn:
            yield conn


class ServiceFactory:
    """
    Factory class to instantiate and manage service instances
    """
    _instances: Dict[str, Any] = {}
    
    @classmethod
    def get_instance(cls, service_class, *args, **kwargs):
        """Get singleton instance of a service"""
        service_name = service_class.__name__
        if service_name not in cls._instances:
            cls._instances[service_name] = service_class(*args, **kwargs)
        return cls._instances[service_name]
        
    @classmethod
    def reset_instances(cls):
        """Reset all instances (for testing)"""
        cls._instances.clear()