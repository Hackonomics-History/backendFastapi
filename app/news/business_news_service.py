import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.news import gemini_adapter, qdrant_service
from app.news.repository import NewsRepository

logger = logging.getLogger(__name__)

UPDATE_INTERVAL_HOURS = 6
CACHE_TTL = 60 * 60 * 6
_CACHE_KEY = "business_news:{}"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _country_name(code: str | None) -> str | None:
    if not code:
        return None
    try:
        from babel import Locale
        return Locale("en").territories.get(code.upper(), code)
    except Exception:
        return code


def _build_response(country_code: str, content: list, created_at: datetime) -> dict:
    next_update = created_at + timedelta(hours=UPDATE_INTERVAL_HOURS)
    return {
        "country_code": country_code,
        "country_name": _country_name(country_code),
        "news": content,
        "last_updated": created_at,
        "next_update": next_update,
        "update_interval_hours": UPDATE_INTERVAL_HOURS,
    }


def _empty_response(country_code: str | None = None) -> dict:
    return {
        "country_code": country_code,
        "country_name": _country_name(country_code),
        "news": [],
        "last_updated": None,
        "next_update": None,
        "update_interval_hours": UPDATE_INTERVAL_HOURS,
    }


def _get_redis():
    import redis
    from app.config import settings
    return redis.from_url(settings.redis_url, decode_responses=True)


def get_user_business_news(country_code: str | None, db: Session) -> dict:
    if not country_code:
        return _empty_response()

    # Check Redis cache first (shared with Kotlin)
    try:
        r = _get_redis()
        cached = r.get(_CACHE_KEY.format(country_code))
        if cached:
            return json.loads(cached)
    except Exception as exc:
        logger.warning("Redis get failed for %s: %s", country_code, exc)

    repo = NewsRepository(db)
    latest = repo.find_latest(country_code)
    if not latest:
        return _empty_response(country_code)

    response = _build_response(country_code, latest.content, latest.created_at)

    try:
        r = _get_redis()
        r.setex(_CACHE_KEY.format(country_code), CACHE_TTL, json.dumps(response, default=str))
    except Exception as exc:
        logger.warning("Redis set failed for %s: %s", country_code, exc)

    return response


def fetch_and_store_news(country_code: str, force: bool, db: Session) -> None:
    repo = NewsRepository(db)

    repo.get_or_create_task_state(country_code)
    db.commit()

    try:
        with db.begin():
            state = repo.lock_task_state_nowait(country_code)
            if state is None:
                logger.warning("No task state row for %s", country_code)
                return

            if state.last_run_at and not force:
                age = _utcnow() - state.last_run_at.replace(tzinfo=timezone.utc)
                if age < timedelta(hours=UPDATE_INTERVAL_HOURS):
                    logger.info("Abort %s: fresh data (age=%s)", country_code, age)
                    return

            now = _utcnow()
            repo.update_task_last_run(country_code, now)
    except OperationalError:
        logger.info("Skip %s: DB lock held by another worker", country_code)
        return

    logger.info("Fetching news → %s (force=%s)", country_code, force)
    try:
        news_items = gemini_adapter.get_country_news(country_code)
    except Exception as exc:
        logger.exception("Gemini fetch failed for %s: %s", country_code, exc)
        return

    if not news_items:
        logger.warning("No valid news returned → %s", country_code)
        return

    now = _utcnow()
    with db.begin():
        repo.save(country_code, news_items, now)
        repo.replace_news_docs(country_code, news_items, now)

    try:
        qdrant_service.upsert_news_docs(country_code, news_items)
    except Exception as exc:
        logger.warning("Qdrant upsert failed for %s: %s", country_code, exc)

    # Invalidate Redis cache so next read picks up fresh data
    try:
        r = _get_redis()
        r.delete(_CACHE_KEY.format(country_code))
    except Exception as exc:
        logger.warning("Redis delete failed for %s: %s", country_code, exc)

    logger.info("News updated → %s", country_code)
