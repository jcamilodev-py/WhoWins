from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exception.errors import ResourceNotFoundException
from app.user.models import User
from app.user.schemas import UserResponse
from app.user.repository import UserRepository


user_repository = UserRepository()

@staticmethod
def _to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user)

async def find_by_id(db: AsyncSession, user_id: UUID) -> UserResponse:
    user = await user_repository.find_by_id(db, user_id)
    
    if user: return _to_response(user)
    raise ResourceNotFoundException("User", "id",user_id)
    
async def find_by_email(db: AsyncSession, email: str) -> UserResponse:
    user = await user_repository.find_by_email(db, email)

    if user: return _to_response(user)
    raise ResourceNotFoundException("User", "email", email)

async def find_by_google_id(db: AsyncSession, google_id: str) -> UserResponse:
    user = await user_repository.find_by_google_id(db, google_id)
    if user: return _to_response(user)

    raise ResourceNotFoundException("User", "google id", google_id)



async def find_by_reset_token(db: AsyncSession, reset_token: str) -> UserResponse:
    user = await user_repository.find_by_reset_token(db, reset_token)

    if user: return _to_response(user)
    raise ResourceNotFoundException("User", "reset token", reset_token)

    

async def exists_by_email(db: AsyncSession, email) -> bool:
    user = await user_repository.exists_by_email(db, email)

    if user: return True 
    raise ResourceNotFoundException("User", "exists by email", "exists by email")
