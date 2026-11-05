"""User / identity schemas."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel, StrictInput


class ProvisionRequest(StrictInput):
    """Profile details supplied at sign-up. Identity (id, email) comes from the token."""

    full_name: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=32)


class UserUpdate(StrictInput):
    full_name: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=32)


class UserResponse(APIModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    phone: str | None
    role: str
    created_at: datetime


class ProvisionResponse(UserResponse):
    created: bool = False


class RoleUpdate(StrictInput):
    role: str = Field(pattern="^(customer|operator|dispatcher|admin)$")
