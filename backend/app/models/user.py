"""User model — mirrors Supabase Auth user records."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    # Relationships
    vessels: Mapped[list["Vessel"]] = relationship(  # noqa: F821
        "Vessel", back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="user"
    )
    cart_items: Mapped[list["CartItem"]] = relationship(  # noqa: F821
        "CartItem", back_populates="user", cascade="all, delete-orphan"
    )
    crew_points: Mapped["CrewPoints | None"] = relationship(  # noqa: F821
        "CrewPoints", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    ai_conversations: Mapped[list["AIConversation"]] = relationship(  # noqa: F821
        "AIConversation", back_populates="user", cascade="all, delete-orphan"
    )
