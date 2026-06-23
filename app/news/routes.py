import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_id
from app.db import SessionLocal, get_db
from app.news import business_news_service, llm_news_service
from app.news.grpc_servicer import _CHAT_EXECUTOR
from app.news.schemas import BusinessNewsResponse, ChatRequest, NewsRefreshResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news", tags=["news"])


def _get_country_code(user_id: str, db: Session) -> str | None:
    from app.user_calendar.models import AccountModel
    account = db.query(AccountModel).filter(AccountModel.ory_identity_id == user_id).first()
    if not account or not account.country_code:
        return None
    return account.country_code


@router.get("/business-news/", response_model=BusinessNewsResponse)
def get_business_news(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    country_code = _get_country_code(user_id, db)
    return business_news_service.get_user_business_news(country_code, db)


@router.post("/business-news/refresh/", response_model=NewsRefreshResponse)
def refresh_business_news(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    from app.common.errors import NotFoundError
    country_code = _get_country_code(user_id, db)
    if not country_code:
        raise NotFoundError("Account or country not found")

    background_tasks.add_task(business_news_service.fetch_and_store_news, country_code, True)
    return {"status": "queued", "country_code": country_code}


@router.post("/chat/stream/")
async def chat_stream(
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    from app.common.errors import NotFoundError
    country_code = _get_country_code(user_id, db)
    if not country_code:
        raise NotFoundError("Account or country not found")

    def _ask() -> dict:
        worker_db = SessionLocal()
        try:
            return llm_news_service.ask(body.question, country_code, worker_db)
        finally:
            worker_db.close()

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_CHAT_EXECUTOR, _ask)

    # TODO(tech-debt): pseudo-SSE — full answer buffered before send. Real token streaming
    # requires a _produce_tokens-style async bridge (separate from this executor pattern).
    def event_stream():
        yield f"data: {result['answer']}\n\n"
        yield "data: done\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
