import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from app.db import SessionLocal
from app.news import groq_adapter
from app.news.business_news_service import fetch_and_store_news
from app.news.hybrid_service import retrieve_context

_CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=4)

logger = logging.getLogger(__name__)

from ai.v1 import ai_pb2, ai_pb2_grpc


def _to_proto_timestamp(dt) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(dt.astimezone(timezone.utc).replace(tzinfo=None))
    return ts


def _produce_tokens(loop, queue, question, contexts, producer_exc) -> None:
    """Drive the blocking Groq stream from a worker thread, handing each token
    back to the event loop. Runs in _CHAT_EXECUTOR, so it must never touch the
    loop directly — only via call_soon_threadsafe. A trailing None sentinel
    signals end-of-stream; producer_exc[0] (if set) carries any failure."""
    try:
        for token in groq_adapter.generate_chat_answer_stream(question, contexts):
            loop.call_soon_threadsafe(queue.put_nowait, token)
    except Exception as exc:
        logger.exception("ChatStream Groq streaming error: %s", exc)
        producer_exc.append(exc)
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, None)


class NewsAiServicer(ai_pb2_grpc.NewsAiServiceServicer):
    """Implements ai.v1.NewsAiService."""

    async def GenerateNews(self, request, context):
        db = SessionLocal()
        try:
            logger.info(
                "GenerateNews request country=%s force=%s",
                request.country_code,
                request.force,
            )
            await asyncio.to_thread(
                fetch_and_store_news,
                country_code=request.country_code,
                force=request.force,
            )
            logger.info("GenerateNews completed country=%s", request.country_code)
            from app.news.repository import NewsRepository
            repo = NewsRepository(db)
            latest = await asyncio.to_thread(repo.find_latest, request.country_code)
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
            context.set_details("Internal server error")
            return ai_pb2.GenerateNewsResponse()
        finally:
            db.close()

    async def ChatStream(self, request, context):
        db = SessionLocal()
        try:
            from app.news.repository import NewsRepository
            repo = NewsRepository(db)
            contexts = retrieve_context(request.question, request.country_code, repo)
        except Exception as exc:
            logger.exception("ChatStream context lookup failed: %s", exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal server error")
            db.close()
            return

        loop = asyncio.get_running_loop()
        # Unbounded queue: tokens are small and the consumer drains them as fast
        # as gRPC flushes to the client, so memory growth is bounded by one LLM
        # response. A maxsize here would force the producer thread to block (it
        # cannot await), so we keep it unbounded for streaming simplicity.
        queue: asyncio.Queue = asyncio.Queue()
        _producer_exc: list[BaseException] = []

        producer = loop.run_in_executor(
            _CHAT_EXECUTOR,
            _produce_tokens,
            loop,
            queue,
            request.question,
            contexts,
            _producer_exc,
        )
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield ai_pb2.ChatStreamChunk(text=item, done=False)
        finally:
            try:
                # Surfaces an unexpected crash in the worker future itself
                # (distinct from a Groq error, which is captured in _producer_exc).
                await producer
            except Exception as exc:
                logger.exception("ChatStream producer future failed: %s", exc)
                _producer_exc.append(exc)
            finally:
                db.close()

        if _producer_exc:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal server error")

        # done=True is sent even after an error so the client always sees an
        # explicit end-of-stream marker; the gRPC status code conveys success/failure.
        yield ai_pb2.ChatStreamChunk(text="", done=True)


def add_to_server(server) -> None:
    ai_pb2_grpc.add_NewsAiServiceServicer_to_server(NewsAiServicer(), server)
