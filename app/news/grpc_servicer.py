import logging
from datetime import timezone

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from app.db import SessionLocal
from app.news import gemini_adapter
from app.news.business_news_service import fetch_and_store_news
from app.news.hybrid_service import retrieve_context

logger = logging.getLogger(__name__)

# Import generated stubs (produced by `make proto-gen` or `./gradlew generateProto`)
try:
    from app.gen.ai.v1 import ai_pb2, ai_pb2_grpc
except ImportError:
    ai_pb2 = None
    ai_pb2_grpc = None
    logger.warning("ai_pb2 stubs not found — run `make proto-gen` first")


def _to_proto_timestamp(dt) -> "Timestamp":
    ts = Timestamp()
    ts.FromDatetime(dt.astimezone(timezone.utc).replace(tzinfo=None))
    return ts


class NewsAiServicer:
    """Implements ai.v1.NewsAiService."""

    def GenerateNews(self, request, context):
        db = SessionLocal()
        try:
            fetch_and_store_news(
                country_code=request.country_code,
                force=request.force,
                db=db,
            )
            from app.news.repository import NewsRepository
            repo = NewsRepository(db)
            latest = repo.find_latest(request.country_code)
            if not latest:
                return ai_pb2.GenerateNewsResponse(
                    country_code=request.country_code,
                    items=[],
                    items_count=0,
                )
            items = [
                ai_pb2.NewsItem(title=it.get("title", ""), description=it.get("description", ""))
                for it in (latest.content or [])
            ]
            return ai_pb2.GenerateNewsResponse(
                country_code=request.country_code,
                items=items,
                generated_at=_to_proto_timestamp(latest.created_at),
                items_count=len(items),
            )
        except Exception as exc:
            logger.exception("GenerateNews failed for %s: %s", request.country_code, exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return ai_pb2.GenerateNewsResponse()
        finally:
            db.close()

    def ChatStream(self, request, context):
        db = SessionLocal()
        try:
            from app.news.repository import NewsRepository
            repo = NewsRepository(db)
            contexts = retrieve_context(request.question, request.country_code, repo)
            answer = gemini_adapter.generate_chat_answer(request.question, contexts)
            yield ai_pb2.ChatStreamChunk(text=answer, done=False)
            yield ai_pb2.ChatStreamChunk(text="", done=True)
        except Exception as exc:
            logger.exception("ChatStream failed: %s", exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
        finally:
            db.close()


def add_to_server(server) -> None:
    if ai_pb2_grpc is None:
        logger.error("Cannot register NewsAiServicer — stubs not generated")
        return
    ai_pb2_grpc.add_NewsAiServiceServicer_to_server(NewsAiServicer(), server)
