import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.user_calendar.models import AccountModel, CalendarEventModel, CategoryModel, UserCalendarModel


class CalendarRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── Account helpers ──────────────────────────────────────────────────────
    def get_account(self, user_id: str) -> AccountModel | None:
        return self.db.query(AccountModel).filter(AccountModel.ory_identity_id == user_id).first()

    # ── UserCalendar ─────────────────────────────────────────────────────────
    def get_or_create_calendar(self, user_id: str) -> UserCalendarModel:
        cal = self.db.query(UserCalendarModel).filter(UserCalendarModel.ory_identity_id == user_id).first()
        if cal:
            return cal
        cal = UserCalendarModel(
            calendar_id=uuid.uuid4(),
            ory_identity_id=user_id,
            provider="LOCAL",
            created_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(cal)
        self.db.flush()
        return cal

    def get_calendar(self, user_id: str) -> UserCalendarModel | None:
        return self.db.query(UserCalendarModel).filter(UserCalendarModel.ory_identity_id == user_id).first()

    def connect_google_calendar(
        self,
        user_id: str,
        google_calendar_id: str,
        access_token: str,
        refresh_token: str | None,
    ) -> UserCalendarModel:
        cal = self.get_or_create_calendar(user_id)
        cal.provider = "GOOGLE"
        cal.google_calendar_id = google_calendar_id
        cal.access_token = access_token
        cal.refresh_token = refresh_token
        self.db.flush()
        return cal

    # ── Categories ───────────────────────────────────────────────────────────
    def create_category(self, user_id: str, name: str, color: str) -> CategoryModel:
        cat = CategoryModel(
            id=uuid.uuid4(),
            ory_identity_id=user_id,
            name=name,
            color=color,
            created_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(cat)
        self.db.flush()
        return cat

    def list_categories(self, user_id: str) -> list[CategoryModel]:
        return (
            self.db.query(CategoryModel)
            .filter(CategoryModel.ory_identity_id == user_id)
            .order_by(CategoryModel.created_at)
            .all()
        )

    def get_category(self, category_id: uuid.UUID, user_id: str) -> CategoryModel | None:
        return (
            self.db.query(CategoryModel)
            .filter(CategoryModel.id == category_id, CategoryModel.ory_identity_id == user_id)
            .first()
        )

    def delete_category(self, category_id: uuid.UUID) -> None:
        self.db.query(CategoryModel).filter(CategoryModel.id == category_id).delete()

    # ── CalendarEvents ───────────────────────────────────────────────────────
    def create_event(
        self,
        user_id: str,
        title: str,
        start_at: datetime,
        end_at: datetime,
        estimated_cost,
        category_ids: list[uuid.UUID],
    ) -> CalendarEventModel:
        cats = (
            self.db.query(CategoryModel)
            .filter(CategoryModel.id.in_(category_ids), CategoryModel.ory_identity_id == user_id)
            .all()
        )
        event = CalendarEventModel(
            id=uuid.uuid4(),
            ory_identity_id=user_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            estimated_cost=estimated_cost,
            created_at=datetime.now(tz=timezone.utc),
            categories=cats,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(self, user_id: str) -> list[CalendarEventModel]:
        return (
            self.db.query(CalendarEventModel)
            .filter(CalendarEventModel.ory_identity_id == user_id)
            .order_by(CalendarEventModel.start_at)
            .all()
        )

    def get_event(self, event_id: uuid.UUID, user_id: str) -> CalendarEventModel | None:
        return (
            self.db.query(CalendarEventModel)
            .filter(
                CalendarEventModel.id == event_id,
                CalendarEventModel.ory_identity_id == user_id,
            )
            .first()
        )

    def update_event(
        self,
        event: CalendarEventModel,
        title: str,
        start_at: datetime,
        end_at: datetime,
        estimated_cost,
        category_ids: list[uuid.UUID],
        user_id: str,
    ) -> CalendarEventModel:
        cats = (
            self.db.query(CategoryModel)
            .filter(CategoryModel.id.in_(category_ids), CategoryModel.ory_identity_id == user_id)
            .all()
        )
        event.title = title
        event.start_at = start_at
        event.end_at = end_at
        event.estimated_cost = estimated_cost
        event.categories = cats
        self.db.flush()
        return event

    def delete_event(self, event_id: uuid.UUID) -> None:
        self.db.query(CalendarEventModel).filter(CalendarEventModel.id == event_id).delete()
