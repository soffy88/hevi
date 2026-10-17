"""
Services package for Hevi microservices architecture
"""
from .registry import service_registry, get_service
from .base import BaseService, ServiceFactory
from .user_service import UserService, user_service
from .task_service import TaskService, task_service
from .cache_service import CacheService, cache_service
from .response_service import ApiResponseService, api_response_service
from .auth_service import AuthServiceMicroservice, auth_microservice
from .rate_limit_service import RateLimitService, rate_limit_service
from .async_task_service import AsyncTaskService, async_task_service
from .middleware import MicroserviceMiddleware, CacheMiddleware, setup_middleware

__all__ = [
    # Main registry
    'service_registry',
    'get_service',
    
    # Base classes
    'BaseService',
    'ServiceFactory',
    
    # Individual services
    'UserService',
    'user_service',
    'TaskService', 
    'task_service',
    'CacheService',
    'cache_service',
    'ApiResponseService',
    'api_response_service',
    'AuthServiceMicroservice',
    'auth_microservice',
    'RateLimitService',
    'rate_limit_service',
    'AsyncTaskService',
    'async_task_service',
    
    # Middleware
    'MicroserviceMiddleware',
    'CacheMiddleware',
    'setup_middleware',
]