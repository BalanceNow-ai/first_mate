"""User profile management. Role and email are not editable here."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUser
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def get_profile(user: CurrentUser) -> User:
    """Get the current user's profile."""
    return user


@router.patch("/me", response_model=UserResponse, dependencies=[Depends(mutation_limit())])
async def update_profile(
    updates: UserUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> User:
    """Update name/phone. Unknown fields (e.g. ``role``) are rejected with 422."""
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return user
