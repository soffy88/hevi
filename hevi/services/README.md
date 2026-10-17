# Hevi Microservices Architecture

This document outlines the microservices architecture implemented in the Hevi project.

## Overview

The Hevi microservices architecture provides a modular, scalable, and maintainable backend structure. The architecture separates concerns into distinct services that can be developed, tested, and deployed independently.

## Service Components

### 1. Base Service (`base.py`)
- Provides common functionality for all services
- Implements database session management
- Defines abstract base class for services

### 2. User Service (`user_service.py`)
- Handles user-related operations
- Manages user creation, authentication, and updates
- Uses database session context managers

### 3. Task Service (`task_service.py`)
- Manages video task lifecycle
- Handles task creation, updates, and status tracking
- Provides user-specific task retrieval

### 4. Cache Service (`cache_service.py`)
- Implements Redis-based caching
- Provides GET/SET/DELETE operations
- Supports serialization of complex objects

### 5. Response Service (`response_service.py`)
- Ensures consistent API responses
- Provides success/error/warning response formats
- Includes pagination support

### 6. Auth Service (`auth_service.py`)
- Handles JWT token creation and verification
- Validates user access to resources
- Integrates with existing auth system

### 7. Rate Limit Service (`rate_limit_service.py`)
- Implements API rate limiting using Redis
- Prevents abuse and ensures fair usage
- Provides rate limit information

### 8. Async Task Service (`async_task_service.py`)
- Manages background tasks
- Provides timeout and retry mechanisms
- Tracks active tasks

## Service Registry

The service registry (`registry.py`) manages all services in the application:

```python
from hevi.services import service_registry, get_service

# Get a service instance
user_svc = get_service('user_service')

# Or use the registry directly
task_svc = service_registry.get_service('task_service')
```

## Middleware Integration

The architecture includes middleware for seamless integration:

- `MicroserviceMiddleware`: Integrates services with FastAPI
- `CacheMiddleware`: Handles response caching
- Automatic rate limiting for protected endpoints

## Usage Examples

### In API Routers

```python
from fastapi import APIRouter, Depends, Request

router = APIRouter(prefix="/example")

@router.get("/users/{user_id}")
async def get_user(request: Request, user_id: str):
    # Access services through request state
    user_service = request.state.services.get_service('user_service')
    user = await user_service.get_user_by_id(user_id)
    return user
```

### In Business Logic

```python
from hevi.services import get_service

async def process_video_task(user_id: str, config: dict):
    # Get required services
    task_service = get_service('task_service')
    cache_service = get_service('cache_service')
    
    # Create and process task
    task = await task_service.create_task(user_id, "video_generation", config)
    
    # Cache the result
    await cache_service.set(f"task_{task['id']}", task, ttl=3600)
    
    return task
```

## Configuration

The services use the existing configuration from `hevi.core.config.Settings`:
- Redis URL for caching and rate limiting
- Database configuration
- JWT settings

## Benefits

1. **Modularity**: Each service handles specific business logic
2. **Scalability**: Services can be scaled independently
3. **Maintainability**: Clear separation of concerns
4. **Testability**: Services can be unit tested in isolation
5. **Consistency**: Standardized response formats and error handling

## Future Enhancements

- Service discovery mechanism
- Inter-service communication patterns
- Circuit breaker patterns
- Distributed tracing
- Health checks for individual services