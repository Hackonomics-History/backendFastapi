import logging

import grpc

from app.db import SessionLocal
from app.user_calendar import gemini_advisor
from app.user_calendar.repository import CalendarRepository

logger = logging.getLogger(__name__)

try:
    from app.gen.ai.v1 import ai_pb2, ai_pb2_grpc
except ImportError:
    ai_pb2 = None
    ai_pb2_grpc = None
    logger.warning("ai_pb2 stubs not found — run `make proto-gen` first")


class CalendarAiServicer:
    """Implements ai.v1.CalendarAiService."""

    def GetAdvice(self, request, context):
        db = SessionLocal()
        try:
            raw = gemini_advisor.analyze_events_and_suggest(
                events_text=request.events_text,
                document_text=request.document_text,
                country_context=request.country_context,
            )
            import json
            try:
                items_data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.error("Gemini returned invalid JSON for CalendarAdvice")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("AI response was malformed")
                return ai_pb2.CalendarAdviceResponse()

            items = [
                ai_pb2.AdviceItem(
                    title=it.get("title", ""),
                    description=it.get("description", ""),
                    event_ids=it.get("event_ids", []),
                    priority=it.get("priority", "medium"),
                )
                for it in (items_data if isinstance(items_data, list) else [])
            ]
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
