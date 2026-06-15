import logging
from datetime import timezone

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from app.db import SessionLocal
from app.news import groq_adapter
from app.news.business_news_service import fetch_and_store_news
from app.news.hybrid_service import retrieve_context

logger = logging.getLogger(__name__)

# Import generated stubs (produced by `make proto-gen` or `./gradlew generateProto`)
try:
    from ai.v1 import ai_pb2, ai_pb2_grpc
except ImportError:
    ai_pb2 = None
    ai_pb2_grpc = None
    logger.warning("ai_pb2 stubs not found — run `buf generate --template buf.gen.kotlin.yaml` first")


def _to_proto_timestamp(dt) -> "Timestamp":
    ts = Timestamp()
    ts.FromDatetime(dt.astimezone(timezone.utc).replace(tzinfo=None))
    return ts


class NewsAiServicer:
    """Implements ai.v1.NewsAiService."""

    def GenerateNews(self, request, context):
        db = SessionLocal()
        try:
            logger.info(
                "GenerateNews request country=%s force=%s",
                request.country_code,
                request.force,
            )
            fetch_and_store_news(
                country_code=request.country_code,
                force=request.force,
            )
            logger.info("GenerateNews completed country=%s", request.country_code)
            from app.news.repository import NewsRepository
            repo = NewsRepository(db)
            latest = repo.find_latest(request.country_code)
            if not latest:
                logger.info("GRPC RESPONSE news_items=0 (no data for %s)", request.country_code)
                return ai_pb2.GenerateNewsResponse(
                    country_code=request.country_code,
                    news_items=[],
                    items_count=0,
                )
            items = [
                ai_pb2.NewsItem(title=it.get("title", ""), description=it.get("description", ""))
                for it in (latest.content or [])
            ]
            logger.info("GRPC RESPONSE news_items=%d", len(items))
            return ai_pb2.GenerateNewsResponse(
                country_code=request.country_code,
                news_items=items,
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
            answer = groq_adapter.generate_chat_answer(request.question, contexts)
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
