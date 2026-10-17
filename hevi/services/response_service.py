"""
API Response service for consistent response formatting across microservices
"""
from typing import Any, Dict, Optional, Union
from datetime import datetime
from enum import Enum
import json


class ApiResponseFormat(Enum):
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


class ApiResponseService:
    """
    Service class for creating consistent API responses across all microservices
    """
    
    @staticmethod
    def success(
        data: Optional[Any] = None, 
        message: Optional[str] = None, 
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a success response
        """
        response = {
            "status": ApiResponseFormat.SUCCESS.value,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        if message:
            response["message"] = message
            
        if meta:
            response["meta"] = meta
            
        return response
    
    @staticmethod
    def error(
        message: str, 
        code: Optional[str] = None, 
        details: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create an error response
        """
        response = {
            "status": ApiResponseFormat.ERROR.value,
            "timestamp": datetime.utcnow().isoformat(),
            "message": message
        }
        
        if code:
            response["code"] = code
            
        if details:
            response["details"] = details
            
        if meta:
            response["meta"] = meta
            
        return response
    
    @staticmethod
    def warning(
        message: str, 
        data: Optional[Any] = None,
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a warning response (operation succeeded with warnings)
        """
        response = {
            "status": ApiResponseFormat.WARNING.value,
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
            "data": data
        }
        
        if meta:
            response["meta"] = meta
            
        return response
    
    @staticmethod
    def paginated_success(
        data: list, 
        page: int, 
        page_size: int, 
        total: int,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a paginated success response
        """
        meta = {
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": (total + page_size - 1) // page_size if page_size > 0 else 0
            }
        }
        
        return ApiResponseService.success(data=data, message=message, meta=meta)
    
    @staticmethod
    def from_exception(
        exc: Exception, 
        message: Optional[str] = None,
        include_details: bool = False
    ) -> Dict[str, Any]:
        """
        Create an error response from an exception
        """
        error_msg = message or str(exc)
        
        if include_details:
            details = {
                "type": type(exc).__name__,
                "args": exc.args,
                "str": str(exc)
            }
            return ApiResponseService.error(message=error_msg, details=details)
        else:
            return ApiResponseService.error(message=error_msg)


# Singleton instance
api_response_service = ApiResponseService()