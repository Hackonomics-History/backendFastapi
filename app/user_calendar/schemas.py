import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class UserCalendarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    calendar_id: uuid.UUID
    ory_identity_id: str
    provider: str
    google_calendar_id: str | None
    access_token: str | None
    refresh_token: str | None
    created_at: datetime


class CategoryCreate(BaseModel):
    name: str
    color: str | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    color: str
    created_at: datetime


class CalendarEventCreate(BaseModel):
    title: str
    start_at: datetime
    end_at: datetime
    estimated_cost: Decimal | None = None
    category_ids: list[uuid.UUID] = []


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime
    estimated_cost: Decimal | None
    created_at: datetime
    category_ids: list[uuid.UUID] = []

    @classmethod
    def from_model(cls, m) -> "CalendarEventResponse":
        return cls(
            id=m.id,
            title=m.title,
            start_at=m.start_at,
            end_at=m.end_at,
            estimated_cost=m.estimated_cost,
            created_at=m.created_at,
            category_ids=[c.id for c in (m.categories or [])],
        )


class CalendarAdviceRequest(BaseModel):
    document_text: str


class CalendarAdviceItem(BaseModel):
    title: str
    description: str | None = None
    event_ids: list[str] = []
    priority: str | None = None
