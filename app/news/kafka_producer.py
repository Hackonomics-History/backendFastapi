import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from aiokafka import AIOKafkaProducer

from app.config import settings
logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await _producer.start()
    return _producer


async def stop_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None


async def publish_result(country_code: str, success: bool, error: str = "") -> None:
    if success:
        event_type = "NEWS_REFRESH_COMPLETED"
        payload: dict = {"country_code": country_code, "items_count": 0}
    else:
        event_type = "NEWS_REFRESH_FAILED"
        payload = {"country_code": country_code, "error_message": error}

    envelope = {
        "event_id": str(uuid4()),
        "aggregate_type": "News",
        "aggregate_id": country_code,
        "event_type": event_type,
        "payload": payload,
        "occurred_at": datetime.now(tz=timezone.utc).isoformat(),
        "service_name": "hackonomics-fastapi",
    }

    try:
        producer = await get_producer()
        await producer.send(
            settings.kafka_news_refresh_result_topic,
            value=envelope,
            key=country_code,
        )
        logger.debug("Published %s for %s", event_type, country_code)
    except Exception as exc:
        logger.warning("Failed to publish %s for %s: %s", event_type, country_code, exc)
