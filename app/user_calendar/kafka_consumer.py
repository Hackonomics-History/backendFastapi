import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings
from app.news import embedder

logger = logging.getLogger(__name__)

COLLECTION_NAME = "user_calendar_events"
VECTOR_DIM = 384  # BAAI/bge-small-en-v1.5


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def _ensure_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )


async def handle_user_activity(msg) -> None:
    envelope = json.loads(msg.value)
    event_type = envelope.get("event_type")

    if event_type != "ACCOUNT_UPDATED":
        return

    payload = envelope.get("payload", {})
    calendar_events = payload.get("calendar_events", [])

    if not calendar_events:
        return

    ory_identity_id = payload.get("ory_identity_id", "")

    texts = [
        f"{e.get('title', '')}\n{e.get('start_at', '')} - {e.get('end_at', '')}"
        for e in calendar_events
    ]
    vectors = await asyncio.to_thread(embedder.embed_texts, texts)

    points = [
        PointStruct(
            id=hash(f"{ory_identity_id}:{e.get('id', i)}") & 0xFFFFFFFFFFFFFFFF,
            vector=vec,
            payload={
                "ory_identity_id": ory_identity_id,
                "event_id": e.get("id"),
                "title": e.get("title", ""),
                "start_at": e.get("start_at"),
                "end_at": e.get("end_at"),
                "estimated_cost": e.get("estimated_cost"),
            },
        )
        for i, (e, vec) in enumerate(zip(calendar_events, vectors))
    ]

    client = get_qdrant_client()
    _ensure_collection(client)
    client.upsert(collection_name=COLLECTION_NAME, points=points)


async def start_user_activities_consumer() -> None:
    consumer = AIOKafkaConsumer(
        "user-activities",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="hackonomics-fastapi-calendar",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("Kafka consumer started on topic user-activities")
    try:
        async for msg in consumer:
            try:
                await handle_user_activity(msg)
                await consumer.commit()
            except Exception as exc:
                logger.error("Skipping commit for failed message: %s", exc)
    except asyncio.CancelledError:
        logger.info("user-activities consumer stopping...")
    finally:
        await consumer.stop()
