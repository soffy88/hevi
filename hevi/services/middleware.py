"""
Middleware service for integrating microservices with FastAPI
"""
from typing import Callable, Awaitable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import time
import logging
from .registry import service_registry
from .rate_limit_service import rate_limit_service
from .cache_service import cache_service


class MicroserviceMiddleware(BaseHTTPMiddleware):
    """
    Middleware to integrate microservices functionality into FastAPI
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.logger = logging.getLogger(self.__class__.__name__)
        
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Add timing
        start_time = time.time()
        
        # Add service registry to request state for easy access in endpoints
        request.state.services = service_registry
        
        # Rate limiting check (for protected endpoints)
        if hasattr(request.app.state, 'rate_limits'):
            endpoint = f"{request.method}:{request.url.path}"
            rate_limits = request.app.state.rate_limits
            
            if endpoint in rate_limits:
                limit_config = rate_limits[endpoint]
                client_ip = self.get_client_ip(request)
                key = f"rate_limit:{client_ip}:{endpoint}"
                
                is_limited, current, reset_time = await rate_limit_service.is_rate_limited(
                    key, 
                    limit_config['max_requests'], 
                    limit_config['window_seconds']
                )
                
                if is_limited:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "Rate limit exceeded",
                            "limit": limit_config['max_requests'],
                            "reset_time": reset_time
                        }
                    )
        
        # Process the request
        try:
            response = await call_next(request)
        except Exception as e:
            self.logger.error(f"Request processing failed: {e}")
            raise
        
        # Add timing info to response headers
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        # Add service info to response headers
        response.headers["X-Microservice-Arch"] = "enabled"
        
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0]
        return request.client.host


class CacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware for handling caching in microservices
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.logger = logging.getLogger(self.__class__.__name__)
        
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Check if this endpoint should be cached
        cache_config = getattr(request.app.state, 'cache_config', {})
        endpoint = f"{request.method}:{request.url.path}"
        
        if endpoint in cache_config:
            cache_settings = cache_config[endpoint]
            if cache_settings.get('enabled', False):
                cache_key = f"response:{endpoint}:{hash(str(dict(request.query_params)))}"
                
                # Try to get cached response
                cached_response = await cache_service.get(cache_key)
                if cached_response:
                    self.logger.info(f"Serving cached response for {cache_key}")
                    return JSONResponse(content=cached_response, status_code=200)
        
        # Process the request normally
        response = await call_next(request)
        
        # Cache the response if applicable
        if endpoint in cache_config:
            cache_settings = cache_config[endpoint]
            if cache_settings.get('enabled', False):
                cache_ttl = cache_settings.get('ttl', 300)  # 5 minutes default
                cache_key = f"response:{endpoint}:{hash(str(dict(request.query_params)))}"
                
                # Extract response content for caching
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk
                    
                # Parse the response body and cache it
                try:
                    import json
                    response_content = json.loads(response_body.decode('utf-8'))
                    await cache_service.set(cache_key, response_content, ttl=cache_ttl)
                    self.logger.info(f"Cached response for {cache_key} with TTL {cache_ttl}s")
                except Exception as e:
                    self.logger.warning(f"Could not cache response: {e}")
        
        return response


def setup_middleware(app):
    """
    Setup middleware for the FastAPI application
    """
    app.add_middleware(MicroserviceMiddleware)
    
    # Add cache middleware if caching is enabled
    cache_enabled = getattr(app.state, 'enable_cache', False)
    if cache_enabled:
        app.add_middleware(CacheMiddleware)