"""User Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None


class UserCreate(UserBase):
    id: uuid.UUID  # From Supabase Auth


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None


class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
