"""
User service implementation for microservices architecture
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..auth.models import User
from ..auth.password import hash_password, verify_password
from .base import BaseService
from ..auth.models import User as UserModel


class UserService(BaseService):
    """
    Service class for user-related operations
    """
    
    async def create_user(self, email: str, password: str, display_name: str) -> Optional[dict]:
        """Create a new user"""
        async with self.get_db_session() as session:
            # Check if user already exists
            existing_user = await session.execute(
                select(UserModel).where(UserModel.email == email)
            )
            existing_user = existing_user.scalar_one_or_none()
            
            if existing_user:
                raise ValueError("Email already registered")
            
            # Hash the password
            hashed_password = hash_password(password)
            
            # Create new user
            user = UserModel(
                email=email,
                password_hash=hashed_password,
                display_name=display_name,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(user)
            await session.flush()  # Get the user ID
            
            # Return user data without sensitive info
            return {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }
    
    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """Retrieve user by email"""
        async with self.get_db_session() as session:
            user = await session.execute(
                select(UserModel).where(UserModel.email == email)
            )
            user = user.scalar_one_or_none()
            
            if not user:
                return None
                
            return {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "password_hash": user.password_hash,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            }
    
    async def authenticate_user(self, email: str, password: str) -> Optional[dict]:
        """Authenticate user credentials"""
        user_data = await self.get_user_by_email(email)
        if not user_data:
            return None
            
        if not verify_password(password, user_data["password_hash"]):
            return None
            
        # Remove password hash from returned data
        del user_data["password_hash"]
        return user_data
    
    async def update_user(self, user_id: str, **updates) -> Optional[dict]:
        """Update user information"""
        async with self.get_db_session() as session:
            # Remove sensitive updates
            updates.pop("password_hash", None)
            updates.pop("id", None)
            updates["updated_at"] = datetime.utcnow()
            
            stmt = (
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(**updates)
            )
            
            result = await session.execute(stmt)
            if result.rowcount == 0:
                return None
                
            # Fetch updated user
            updated_user = await session.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            updated_user = updated_user.scalar_one()
            
            return {
                "id": str(updated_user.id),
                "email": updated_user.email,
                "display_name": updated_user.display_name,
                "created_at": updated_user.created_at.isoformat() if updated_user.created_at else None,
                "updated_at": updated_user.updated_at.isoformat() if updated_user.updated_at else None
            }


# Singleton instance
user_service = UserService()