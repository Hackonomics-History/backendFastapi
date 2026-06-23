"""
TDD Red Phase — user-activities Consumer & Calendar Qdrant Partitioning
======================================================================

Task 1: Implement a Kafka consumer for the `user-activities` topic that
processes ACCOUNT_UPDATED events and stores calendar data in a dedicated
Qdrant collection named `user_calendar_events`.

Architecture context:
- `business_news` Qdrant collection: already exists for news RAG pipeline
- `user_calendar_events` Qdrant collection: NEW — per-user calendar knowledge
- Partitioning strategy: Collection Separation (not payload filtering)

Missing implementation (must NOT exist yet — ensures Red fails):
- app/user_calendar/kafka_consumer.py does not exist
- No `handle_user_activity()` async handler function
- No `start_user_activities_consumer()` function
- No upsert logic targeting `user_calendar_events`

ALL TESTS IN THIS FILE MUST FAIL AGAINST THE CURRENT IMPLEMENTATION.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

USER_ACTIVITIES_TOPIC = "user-activities"
CALENDAR_COLLECTION = "user_calendar_events"
NEWS_COLLECTION = "business_news"


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def account_updated_kafka_message():
    """ACCOUNT_UPDATED event carrying two calendar events for a user."""
    msg = MagicMock()
    msg.value = json.dumps(
        {
            "event_type": "ACCOUNT_UPDATED",
            "aggregate_id": "kratos-user-uuid-1234",
            "payload": {
                "ory_identity_id": "kratos-user-uuid-1234",
                "calendar_events": [
                    {
                        "id": "event-uuid-abc",
                        "title": "Team Sprint Planning",
                        "start_at": "2026-06-21T09:00:00Z",
                        "end_at": "2026-06-21T10:00:00Z",
                        "estimated_cost": None,
                    },
                    {
                        "id": "event-uuid-def",
                        "title": "Budget Review Q2",
                        "start_at": "2026-06-22T14:00:00Z",
                        "end_at": "2026-06-22T15:30:00Z",
                        "estimated_cost": 150.00,
                    },
                ],
            },
        }
    ).encode("utf-8")
    return msg


@pytest.fixture
def account_updated_no_calendar_message():
    """ACCOUNT_UPDATED event where calendar_events is empty — must be a no-op."""
    msg = MagicMock()
    msg.value = json.dumps(
        {
            "event_type": "ACCOUNT_UPDATED",
            "aggregate_id": "kratos-user-uuid-5678",
            "payload": {
                "ory_identity_id": "kratos-user-uuid-5678",
                "calendar_events": [],
            },
        }
    ).encode("utf-8")
    return msg


@pytest.fixture
def unknown_event_kafka_message():
    """Non-ACCOUNT_UPDATED event type — handler must silently ignore it."""
    msg = MagicMock()
    msg.value = json.dumps(
        {
            "event_type": "USER_DELETED",
            "aggregate_id": "kratos-user-uuid-9999",
            "payload": {},
        }
    ).encode("utf-8")
    return msg


# ─── Test Class 1: Assert 1 — Qdrant upsert IS called ────────────────────────


class TestQdrantUpsertCalledOnAccountUpdated:
    """
    Assert 1: When handle_user_activity() processes an ACCOUNT_UPDATED message
    that contains calendar_events, qdrant_client.upsert() MUST be called.

    RED: All tests fail with ImportError because the module does not exist.
    """

    @pytest.mark.asyncio
    async def test_should_call_qdrant_upsert_when_account_updated_event_arrives(
        self, account_updated_kafka_message
    ):
        """
        Assert 1: qdrant_client.upsert() must be called exactly once when
        an ACCOUNT_UPDATED event with non-empty calendar_events is processed.

        RED: FAILS — ImportError on the import below, because
        app/user_calendar/kafka_consumer.py does not exist.

        Fix (green phase):
          1. Create app/user_calendar/kafka_consumer.py
          2. Implement async handle_user_activity(msg):
             - Parse the JSON envelope
             - Check event_type == "ACCOUNT_UPDATED"
             - Embed calendar event text into vectors
             - Call qdrant_client.upsert(collection_name="user_calendar_events", ...)
        """
        from app.user_calendar.kafka_consumer import handle_user_activity  # noqa: F401 — DOES NOT EXIST

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.upsert = MagicMock()

        with patch(
            "app.user_calendar.kafka_consumer.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            await handle_user_activity(account_updated_kafka_message)

        mock_qdrant_client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_call_upsert_with_points_derived_from_calendar_events(
        self, account_updated_kafka_message
    ):
        """
        The upsert call must include vector points built from the calendar events
        in the payload — not an empty points list.

        RED: FAILS — ImportError (module does not exist).
        """
        from app.user_calendar.kafka_consumer import handle_user_activity  # noqa: F401 — DOES NOT EXIST

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.upsert = MagicMock()

        with patch(
            "app.user_calendar.kafka_consumer.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            await handle_user_activity(account_updated_kafka_message)

        call_kwargs = mock_qdrant_client.upsert.call_args
        assert call_kwargs is not None, (
            "qdrant_client.upsert() was never called. "
            "handle_user_activity() must call upsert() for ACCOUNT_UPDATED events."
        )
        points = call_kwargs.kwargs.get("points") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert points, (
            "upsert() was called but `points` was empty or missing. "
            "Each calendar event must produce at least one PointStruct."
        )


# ─── Test Class 2: Assert 2 — Exact collection name verified ─────────────────


class TestQdrantCollectionNameIsUserCalendarEvents:
    """
    Assert 2: The collection_name argument passed to qdrant_client.upsert()
    MUST be exactly "user_calendar_events", never "business_news" or any other.

    RED: All tests fail with ImportError (module does not exist).
    """

    @pytest.mark.asyncio
    async def test_should_pass_user_calendar_events_as_collection_name(
        self, account_updated_kafka_message
    ):
        """
        Assert 2 (primary): upsert() must receive collection_name="user_calendar_events".

        RED: FAILS — ImportError on import; then would also fail because the
        implementation does not exist to pass the correct collection name.

        Fix (green phase): when calling qdrant_client.upsert(), pass
        collection_name="user_calendar_events" (dedicated calendar partition).
        """
        from app.user_calendar.kafka_consumer import handle_user_activity  # noqa: F401 — DOES NOT EXIST

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.upsert = MagicMock()

        with patch(
            "app.user_calendar.kafka_consumer.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            await handle_user_activity(account_updated_kafka_message)

        call_kwargs = mock_qdrant_client.upsert.call_args
        assert call_kwargs is not None, (
            "qdrant_client.upsert() was never called.\n"
            "Fix: implement handle_user_activity() to call upsert() with "
            "collection_name='user_calendar_events'."
        )

        actual_collection = call_kwargs.kwargs.get("collection_name") or (
            call_kwargs.args[0] if call_kwargs.args else None
        )
        assert actual_collection == CALENDAR_COLLECTION, (
            f"Expected collection_name='{CALENDAR_COLLECTION}', "
            f"but got '{actual_collection}'.\n"
            "Calendar events MUST be stored in the dedicated 'user_calendar_events' "
            "collection — not in 'business_news' or any other collection.\n"
            "This enforces the Collection Separation partitioning strategy."
        )

    @pytest.mark.asyncio
    async def test_should_not_use_business_news_collection_for_calendar_data(
        self, account_updated_kafka_message
    ):
        """
        Regression guard: calendar data MUST NOT bleed into the business_news
        collection used by the news RAG pipeline.

        RED: FAILS — ImportError (module does not exist).
        """
        from app.user_calendar.kafka_consumer import handle_user_activity  # noqa: F401 — DOES NOT EXIST

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.upsert = MagicMock()

        with patch(
            "app.user_calendar.kafka_consumer.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            await handle_user_activity(account_updated_kafka_message)

        call_kwargs = mock_qdrant_client.upsert.call_args
        if call_kwargs is not None:
            actual_collection = call_kwargs.kwargs.get("collection_name") or (
                call_kwargs.args[0] if call_kwargs.args else None
            )
            assert actual_collection != NEWS_COLLECTION, (
                f"Calendar events were incorrectly stored in '{NEWS_COLLECTION}'. "
                "Use collection separation: create a dedicated 'user_calendar_events' collection."
            )


# ─── Test Class 3: Event routing — ignore non-calendar events ────────────────


class TestUserActivityEventRouting:
    """
    Verifies that only ACCOUNT_UPDATED events with calendar data trigger
    Qdrant upsert. Other event types and empty payloads must be no-ops.

    RED: All tests fail with ImportError (module does not exist).
    """

    @pytest.mark.asyncio
    async def test_should_not_call_upsert_for_unknown_event_type(
        self, unknown_event_kafka_message
    ):
        """
        Non-ACCOUNT_UPDATED events (e.g., USER_DELETED) must not trigger
        any Qdrant write.

        RED: FAILS — ImportError (module does not exist).
        """
        from app.user_calendar.kafka_consumer import handle_user_activity  # noqa: F401 — DOES NOT EXIST

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.upsert = MagicMock()

        with patch(
            "app.user_calendar.kafka_consumer.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            await handle_user_activity(unknown_event_kafka_message)

        mock_qdrant_client.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_not_call_upsert_when_calendar_events_list_is_empty(
        self, account_updated_no_calendar_message
    ):
        """
        ACCOUNT_UPDATED with an empty calendar_events list must not call
        upsert — there are no vectors to store.

        RED: FAILS — ImportError (module does not exist).
        """
        from app.user_calendar.kafka_consumer import handle_user_activity  # noqa: F401 — DOES NOT EXIST

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.upsert = MagicMock()

        with patch(
            "app.user_calendar.kafka_consumer.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            await handle_user_activity(account_updated_no_calendar_message)

        mock_qdrant_client.upsert.assert_not_called()


# ─── Test Class 4: Consumer infrastructure — topic subscription ───────────────


class TestUserActivitiesConsumerInfrastructure:
    """
    Verifies that the Kafka consumer subscribes to the correct 'user-activities'
    topic (not the news topic) and uses the correct consumer group.

    RED: All tests fail with ImportError (module does not exist).
    """

    @pytest.mark.asyncio
    async def test_should_subscribe_to_user_activities_kafka_topic(self):
        """
        AIOKafkaConsumer must be instantiated with 'user-activities' as the
        subscribed topic — distinct from 'news.refresh.request'.

        RED: FAILS — ImportError (module does not exist).
        """
        from app.user_calendar import kafka_consumer as uc_kafka  # noqa: F401 — DOES NOT EXIST

        mock_consumer = MagicMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.commit = AsyncMock()
        mock_consumer.__aiter__ = MagicMock(return_value=iter([]))

        with patch(
            "app.user_calendar.kafka_consumer.AIOKafkaConsumer",
            return_value=mock_consumer,
        ) as mock_aio:
            try:
                await uc_kafka.start_user_activities_consumer()
            except Exception:
                pass

        assert mock_aio.called, "AIOKafkaConsumer was never instantiated."
        subscribed_topics = mock_aio.call_args.args
        assert USER_ACTIVITIES_TOPIC in subscribed_topics, (
            f"Consumer must subscribe to '{USER_ACTIVITIES_TOPIC}', "
            f"but was subscribed to: {subscribed_topics}"
        )
