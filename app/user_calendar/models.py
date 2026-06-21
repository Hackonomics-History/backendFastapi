import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Table, Text, UniqueConstraint
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# M2M join table — matches Django's auto-generated name
calendar_event_category = Table(
    "calendar_event_categories",
    Base.metadata,
    Column("calendarevent_id", UUID(as_uuid=True), ForeignKey("calendar_event.id"), primary_key=True),
    Column("category_id", UUID(as_uuid=True), ForeignKey("calendar_category.id"), primary_key=True),
)


class AccountModel(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    ory_identity_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)


class UserCalendarModel(Base):
    __tablename__ = "user_calendar"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    ory_identity_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), default="LOCAL")
    google_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CategoryModel(Base):
    __tablename__ = "calendar_category"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ory_identity_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    color: Mapped[str] = mapped_column(String(50), default="#3b82f6")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["CalendarEventModel"]] = relationship(
        secondary=calendar_event_category, back_populates="categories"
    )


class CalendarEventModel(Base):
    __tablename__ = "calendar_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ory_identity_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    categories: Mapped[list[CategoryModel]] = relationship(
        secondary=calendar_event_category, back_populates="events"
    )
