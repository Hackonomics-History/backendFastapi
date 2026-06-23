import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.news.business_news_service import fetch_and_store_news
from app.news.kafka_producer import publish_result

logger = logging.getLogger(__name__)


async def start_consumer() -> None:
    consumer = AIOKafkaConsumer(
        settings.kafka_news_refresh_request_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("Kafka consumer started on topic %s", settings.kafka_news_refresh_request_topic)
    try:
        async for msg in consumer:
            try:
                await _handle(msg)
                await consumer.commit()
            except Exception as exc:
                logger.error("Skipping commit for failed message: %s", exc)
    except asyncio.CancelledError:
        logger.info("Kafka consumer stopping...")
    finally:
        await consumer.stop()


async def _handle(msg) -> None:
    try:
        envelope = json.loads(msg.value)
        event_type = envelope.get("event_type")
        country_code = envelope.get("aggregate_id", "")
        payload = envelope.get("payload", {})

        if event_type != "NEWS_REFRESH_REQUESTED":
            return

        force = payload.get("force", False)
        logger.info("Consuming NEWS_REFRESH_REQUESTED for %s (force=%s)", country_code, force)

        await asyncio.to_thread(fetch_and_store_news, country_code, force)

        await publish_result(country_code, success=True)
    except Exception as exc:
        logger.exception("Failed to handle news refresh request: %s", exc)
        try:
            country_code = json.loads(msg.value).get("aggregate_id", "")
            await publish_result(country_code, success=False, error=str(exc))
        except Exception:
            pass
        raise
