"""
Authentication and Authorization service for microservices architecture
"""
from typing import Any

import jwt

from ..auth.jwt_handler import decode_access_token, sign_access_token
from ..core.config import settings
from .base import BaseService


class AuthServiceMicroservice(BaseService):
    """
    Authentication and Authorization service for microservices architecture
    """
    
    def __init__(self) -> None:
        super().__init__()
        self.jwt_secret = settings.jwt_secret
        self.jwt_algorithm = settings.jwt_algorithm
        self.token_expiry = settings.jwt_expire_minutes
        
    async def create_token(self, user_data: dict[str, Any]) -> str:
        """
        Create a JWT token for a user
        """
        try:
            user_id = user_data.get("sub") or user_data.get("user_id") or user_data.get("id")
            if user_id is None or str(user_id).strip() == "":
                raise ValueError("user_data must include sub, user_id, or id")
            return sign_access_token(str(user_id))
        except Exception as e:
            self.logger.error(f"Token creation failed: {e}")
            raise
    
    async def verify_token(self, token: str) -> dict[str, Any] | None:
        """
        Verify a JWT token and return the payload
        """
        try:
            return decode_access_token(token)
        except jwt.ExpiredSignatureError:
            self.logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            self.logger.warning(f"Token verification failed: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error during token verification: {e}")
            return None
    
    async def validate_user_access(self, token: str, resource: str, action: str = "read") -> bool:
        """
        Validate if a user has access to a specific resource and action
        """
        try:
            payload = await self.verify_token(token)
            if not payload:
                return False
            
            user_id = payload.get("sub")
            # Basic validation - in a real implementation, this would check
            # against a permission matrix or RBAC system. For now, ensure the
            # token identifies a user.
            return bool(user_id)
            
        except Exception as e:
            self.logger.error(f"Access validation failed: {e}")
            return False
    
    async def refresh_token(self, refresh_token: str) -> str | None:
        """
        Refresh an access token using a refresh token
        """
        # In a real implementation, this would validate the refresh token
        # and generate a new access token
        # For now, we'll just return None as refresh tokens aren't implemented
        # in the base auth system
        return None


# Singleton instance
auth_microservice = AuthServiceMicroservice()