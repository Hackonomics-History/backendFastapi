import json
import logging

import grpc

from app.db import SessionLocal
from app.user_calendar import groq_advisor
from app.user_calendar.repository import CalendarRepository

logger = logging.getLogger(__name__)

try:
    from ai.v1 import ai_pb2, ai_pb2_grpc
except ImportError:
    ai_pb2 = None
    ai_pb2_grpc = None
    logger.warning("ai_pb2 stubs not found — run `buf generate --template buf.gen.kotlin.yaml` first")


class CalendarAiServicer:
    """Implements ai.v1.CalendarAiService."""

    def GetAdvice(self, request, context):
        db = SessionLocal()
        try:
            raw = groq_advisor.analyze_events_and_suggest(
                events_text=request.events_text,
                document_text=request.document_text,
                country_context=request.country_context,
            )
            logger.info("GROQ RAW RESPONSE length=%d content=%s", len(raw or ""), raw)

            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.error("JSON parse failed: %s | raw=%s", exc, raw)
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("AI response was malformed JSON")
                return ai_pb2.CalendarAdviceResponse()

            logger.info("PARSED JSON type=%s value=%s", type(parsed).__name__, parsed)

            # Groq json_object mode always returns a dict, never a bare array.
            # The prompt uses {"advice": [...]} as the wrapper key.
            # Fallback: also accept a bare list (future-proof if response_format changes).
            if isinstance(parsed, list):
                items_list = parsed
            elif isinstance(parsed, dict):
                # Try common wrapper keys the model might choose
                items_list = (
                    parsed.get("advice")
                    or parsed.get("items")
                    or parsed.get("suggestions")
                    or parsed.get("recommendations")
                    or []
                )
                if not isinstance(items_list, list):
                    logger.error("Expected list under advice key, got %s", type(items_list).__name__)
                    items_list = []
            else:
                logger.error("Unexpected parsed type: %s", type(parsed).__name__)
                items_list = []

            logger.info("ADVICE ITEM COUNT=%d", len(items_list))

            items = [
                ai_pb2.AdviceItem(
                    title=it.get("title", ""),
                    description=it.get("description", ""),
                    event_ids=it.get("event_ids", []),
                    priority=it.get("priority", "medium"),
                )
                for it in items_list
                if isinstance(it, dict)
            ]

            logger.info("GRPC RESPONSE items=%d", len(items))
            return ai_pb2.CalendarAdviceResponse(items=items)
        except Exception as exc:
            logger.exception("GetAdvice failed: %s", exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return ai_pb2.CalendarAdviceResponse()
        finally:
            db.close()


def add_to_server(server) -> None:
    if ai_pb2_grpc is None:
        logger.error("Cannot register CalendarAiServicer — stubs not generated")
        return
    ai_pb2_grpc.add_CalendarAiServiceServicer_to_server(CalendarAiServicer(), server)
