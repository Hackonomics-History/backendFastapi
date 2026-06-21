import json
import logging
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_id
from app.common.errors import ForbiddenError, NotFoundError, ValidationError
from app.db import get_db
from app.user_calendar import groq_advisor
from app.user_calendar.google_oauth import build_google_calendar_flow
from app.user_calendar.repository import CalendarRepository
from app.user_calendar.schemas import (
    CalendarAdviceRequest,
    CalendarEventCreate,
    CalendarEventResponse,
    CategoryCreate,
    CategoryResponse,
    UserCalendarResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])


# ── UserCalendar ─────────────────────────────────────────────────────────────

@router.post("/init/", response_model=UserCalendarResponse, status_code=status.HTTP_201_CREATED)
def init_calendar(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    cal = repo.get_or_create_calendar(user_id)
    db.commit()
    db.refresh(cal)
    return cal


@router.get("/me/", response_model=UserCalendarResponse)
def get_my_calendar(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    cal = repo.get_calendar(user_id)
    if not cal:
        raise NotFoundError("Calendar not found")
    return cal


# ── Google OAuth ─────────────────────────────────────────────────────────────

@router.get("/oauth/login/")
def google_oauth_login(user_id: str = Depends(get_current_user_id)):
    flow = build_google_calendar_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=user_id,
    )
    return {"redirect_url": auth_url}


@router.get("/oauth/callback/")
def google_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    state = request.query_params.get("state")
    if not state:
        raise ValidationError("Missing state parameter")

    flow = build_google_calendar_flow(state=state)
    flow.fetch_token(authorization_response=str(request.url))
    credentials = flow.credentials

    user_id = state
    repo = CalendarRepository(db)
    existing = repo.get_calendar(user_id)
    cal = repo.connect_google_calendar(
        user_id=user_id,
        google_calendar_id="primary",
        access_token=credentials.token,
        refresh_token=credentials.refresh_token or (existing.refresh_token if existing else None),
    )
    db.commit()
    db.refresh(cal)
    return cal


# ── Categories ───────────────────────────────────────────────────────────────

@router.post("/categories/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    color = body.color or "#3b82f6"
    cat = repo.create_category(user_id, body.name, color)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("/categories/", response_model=list[CategoryResponse])
def list_categories(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    return repo.list_categories(user_id)


@router.delete("/categories/{category_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    cat = repo.get_category(category_id, user_id)
    if not cat:
        raise NotFoundError("Category not found")
    repo.delete_category(category_id)
    db.commit()


# ── CalendarEvents ────────────────────────────────────────────────────────────

@router.post("/events/", response_model=CalendarEventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    body: CalendarEventCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not body.title or not body.title.strip():
        raise ValidationError("Title is required")
    if body.end_at <= body.start_at:
        raise ValidationError("end_at must be after start_at")

    repo = CalendarRepository(db)
    event = repo.create_event(
        user_id=user_id,
        title=body.title.strip(),
        start_at=body.start_at,
        end_at=body.end_at,
        estimated_cost=body.estimated_cost,
        category_ids=body.category_ids,
    )
    db.commit()
    db.refresh(event)
    return CalendarEventResponse.from_model(event)


@router.get("/events/", response_model=list[CalendarEventResponse])
def list_events(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    events = repo.list_events(user_id)
    return [CalendarEventResponse.from_model(e) for e in events]


@router.put("/events/{event_id}/", response_model=CalendarEventResponse)
def update_event(
    event_id: uuid.UUID,
    body: CalendarEventCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not body.title or not body.title.strip():
        raise ValidationError("Title is required")
    if body.end_at <= body.start_at:
        raise ValidationError("end_at must be after start_at")

    repo = CalendarRepository(db)
    event = repo.get_event(event_id, user_id)
    if not event:
        raise NotFoundError("Event not found")

    updated = repo.update_event(
        event=event,
        title=body.title.strip(),
        start_at=body.start_at,
        end_at=body.end_at,
        estimated_cost=body.estimated_cost,
        category_ids=body.category_ids,
        user_id=user_id,
    )
    db.commit()
    db.refresh(updated)
    return CalendarEventResponse.from_model(updated)


@router.delete("/events/{event_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    event = repo.get_event(event_id, user_id)
    if not event:
        raise NotFoundError("Event not found")
    repo.delete_event(event_id)
    db.commit()


# ── AI Advisor ────────────────────────────────────────────────────────────────

@router.post("/advice/")
def calendar_advice(
    body: CalendarAdviceRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = CalendarRepository(db)
    account = repo.get_account(user_id)
    country_context = ""
    if account and account.country_code:
        country_context = f"{account.country_code} ({account.currency or ''})"

    events = repo.list_events(user_id)
    events_text = "\n".join(
        f"- EVENT_ID: {e.id} | TITLE: {e.title} | START: {e.start_at}"
        for e in events
    ) or "No events"

    try:
        raw_advice = groq_advisor.analyze_events_and_suggest(
            events_text=events_text,
            document_text=body.document_text,
            country_context=country_context,
        )
        try:
            advice_data = json.loads(raw_advice)
        except (json.JSONDecodeError, TypeError):
            logger.error("Groq returned invalid JSON: %s", raw_advice)
            return JSONResponse(
                status_code=424,
                content={"error": "AI response was malformed. Please try again."},
            )
        return {"advice": advice_data}
    except Exception as exc:
        logger.error("CalendarAdvisor error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "The AI advisor is currently unavailable. Please try again in a few minutes."},
        )
