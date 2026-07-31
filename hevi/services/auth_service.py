"""
Authentication and Authorization service for microservices architecture
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import jwt
from ..auth.jwt_handler import create_access_token, verify_token
from ..auth.auth_service import AuthService
from .base import BaseService
from ..core.config import settings


class AuthServiceMicroservice(BaseService):
    """
    Authentication and Authorization service for microservices architecture
    """
    
    def __init__(self):
        super().__init__()
        self.jwt_secret = settings.jwt_secret
        self.jwt_algorithm = settings.jwt_algorithm
        self.token_expiry = settings.jwt_expire_minutes
        
    async def create_token(self, user_data: Dict[str, Any]) -> str:
        """
        Create a JWT token for a user
        """
        try:
            token = create_access_token(
                data=user_data,
                expires_delta=timedelta(minutes=self.token_expiry)
            )
            return token
        except Exception as e:
            self.logger.error(f"Token creation failed: {e}")
            raise
    
    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify a JWT token and return the payload
        """
        try:
            payload = verify_token(token)
            return payload
        except jwt.ExpiredSignatureError:
            self.logger.warning("Token has expired")
            return None
        except jwt.JWTError as e:
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
            if not user_id:
                return False
            
            # Basic validation - in a real implementation, this would check
            # against a permission matrix or RBAC system
            # For now, just ensure the user exists and token is valid
            return True
            
        except Exception as e:
            self.logger.error(f"Access validation failed: {e}")
            return False
    
    async def refresh_token(self, refresh_token: str) -> Optional[str]:
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