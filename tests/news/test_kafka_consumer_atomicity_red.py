"""
TDD Red Phase — News Pipeline Distributed Transaction Atomicity
===============================================================

Issue 2 & Issue 3-2: Two critical bugs in the news Kafka consumer pipeline.

Bug 1 — Stale Vector (DB/Qdrant data inconsistency):
  In _fetch_and_store_impl (business_news_service.py):
    1. `with db.begin():` commits BusinessNews to Postgres — THEN
    2. qdrant_service.upsert_news_docs() is called OUTSIDE the transaction.
  If Qdrant upsert raises, only a warning is logged and the function returns
  normally. Postgres has the new row; Qdrant does not → stale/split-brain data.

Bug 2 — Unconditional Kafka commit (message loss):
  In start_consumer (kafka_consumer.py), consumer.commit() is called
  unconditionally after _handle(). _handle() catches ALL exceptions internally
  and never re-raises. So even when processing fails, Kafka sees the message as
  successfully processed → the message is permanently lost.

ALL TESTS IN THIS FILE MUST FAIL AGAINST THE CURRENT IMPLEMENTATION.
"""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────


class SpySession:
    """
    SQLAlchemy Session test-double that tracks whether BusinessNews objects
    were committed inside a `with session.begin():` block.

    Mirrors SQLAlchemy transaction semantics:
      - begin() context exits normally  → data is "committed"
      - begin() context exits with raise → data is "rolled back"
    """

    def __init__(self):
        self.committed_news_count = 0
        self._pending_news_count = 0

    @contextmanager
    def begin(self):
        self._pending_news_count = 0
        try:
            yield
            # Successful exit: treat as commit
            self.committed_news_count += self._pending_news_count
        except Exception:
            # Exception exit: treat as rollback — discard pending, re-raise
            raise
        finally:
            self._pending_news_count = 0

    def add(self, obj):
        from app.news.models import BusinessNews
        if isinstance(obj, BusinessNews):
            self._pending_news_count += 1

    def flush(self):
        pass

    def commit(self):
        # Explicit commit outside a begin() block (used for task-state init)
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def query(self, _model=None):
        return MagicMock()

    def execute(self, _stmt=None, _params=None):
        return MagicMock()


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_news_items():
    return [
        {
            "title": "US Market Rally",
            "description": "Stocks rose 3% on strong earnings.",
            "url": "https://example.com/1",
        },
        {
            "title": "Fed Rate Decision",
            "description": "Federal Reserve holds rates steady.",
            "url": "https://example.com/2",
        },
    ]


@pytest.fixture
def news_refresh_kafka_message():
    """Kafka message that triggers a NEWS_REFRESH_REQUESTED event for 'US'."""
    msg = MagicMock()
    msg.value = json.dumps(
        {
            "event_type": "NEWS_REFRESH_REQUESTED",
            "aggregate_id": "US",
            "payload": {"force": True},
        }
    ).encode("utf-8")
    return msg


# ─── Test Class 1: DB Rollback on Qdrant Failure ──────────────────────────────


class TestDbTransactionRollbackOnQdrantFailure:
    """
    Verifies atomicity: when Qdrant upsert fails, the Postgres transaction must
    also be rolled back — no partial commit.

    Current behaviour (BUG): the `with db.begin():` block exits normally and
    commits BusinessNews to Postgres BEFORE upsert_news_docs() is called.
    The Qdrant exception is then caught with only a warning log, so Postgres
    ends up with new rows that Qdrant does not have.
    """

    def test_should_not_persist_news_to_db_when_qdrant_upsert_fails(
        self, sample_news_items
    ):
        """
        Assert 1: After a Qdrant upsert failure, no BusinessNews row should be
        committed to the database.

        RED: FAILS because the current code structure is:
            with db.begin():          # ← commits here (BEFORE qdrant)
                repo.save(...)
                repo.replace_news_docs(...)
            # ← transaction already committed
            try:
                qdrant_service.upsert_news_docs(...)  # ← fails here (too late)
            except Exception:
                logger.warning(...)   # ← only warned, no rollback possible

        FIX (green phase): move qdrant_service.upsert_news_docs() INSIDE
        `with db.begin():` so any Qdrant failure triggers automatic DB rollback.
        """
        from app.news.business_news_service import _fetch_and_store_impl
        from app.news.repository import NewsRepository

        spy_db = SpySession()

        # Simulate a task-state row that allows the update path to proceed
        mock_state = MagicMock()
        mock_state.last_run_at = None  # no previous run → always proceed

        def mock_save(country_code, news_items, now):
            """Mimics NewsRepository.save: adds a BusinessNews to the session."""
            from app.news.models import BusinessNews

            news = BusinessNews(
                country_code=country_code, content=news_items, created_at=now
            )
            spy_db.add(news)
            spy_db.flush()
            return news

        with (
            patch.object(
                NewsRepository,
                "get_or_create_task_state",
                return_value=MagicMock(),
            ),
            patch.object(
                NewsRepository,
                "lock_task_state_nowait",
                return_value=mock_state,
            ),
            patch.object(NewsRepository, "update_task_last_run", return_value=None),
            patch.object(NewsRepository, "save", side_effect=mock_save),
            patch.object(NewsRepository, "replace_news_docs", return_value=None),
            patch(
                "app.news.business_news_service.groq_adapter.get_country_news",
                return_value=sample_news_items,
            ),
            patch(
                "app.news.business_news_service.qdrant_service.upsert_news_docs",
                side_effect=Exception(
                    "Qdrant connection refused: upsert failed"
                ),
            ),
            patch(
                "app.news.business_news_service._get_redis",
                side_effect=Exception("No Redis in test"),
            ),
        ):
            try:
                _fetch_and_store_impl("US", force=True, db=spy_db)
            except Exception:
                # An exception from _fetch_and_store_impl is acceptable in the
                # green phase; what matters here is the DB commit count.
                pass

        assert spy_db.committed_news_count == 0, (
            f"Expected 0 BusinessNews rows committed after Qdrant failure, "
            f"but {spy_db.committed_news_count} row(s) were committed.\n"
            "Root cause: the current code calls `with db.begin():` (which commits)\n"
            "BEFORE calling qdrant_service.upsert_news_docs(). A Qdrant failure\n"
            "therefore cannot roll back the already-committed Postgres transaction.\n"
            "Fix: move the Qdrant upsert inside the `with db.begin():` block so\n"
            "a failure triggers automatic Postgres rollback."
        )

    def test_fetch_store_impl_should_raise_when_qdrant_upsert_fails(
        self, sample_news_items
    ):
        """
        _fetch_and_store_impl must propagate (not swallow) the Qdrant exception
        so that the Kafka consumer layer can detect the failure and skip commit().

        RED: FAILS because the current code wraps the Qdrant call in try/except
        and only logs a warning, causing the function to return normally as if
        everything succeeded. The Kafka consumer cannot distinguish success from
        failure, so it always calls consumer.commit().
        """
        from app.news.business_news_service import _fetch_and_store_impl
        from app.news.repository import NewsRepository

        spy_db = SpySession()

        mock_state = MagicMock()
        mock_state.last_run_at = None

        qdrant_error = Exception("Qdrant: upsert failed — service unavailable")

        with (
            patch.object(
                NewsRepository,
                "get_or_create_task_state",
                return_value=MagicMock(),
            ),
            patch.object(
                NewsRepository,
                "lock_task_state_nowait",
                return_value=mock_state,
            ),
            patch.object(NewsRepository, "update_task_last_run", return_value=None),
            patch.object(NewsRepository, "save", return_value=MagicMock()),
            patch.object(NewsRepository, "replace_news_docs", return_value=None),
            patch(
                "app.news.business_news_service.groq_adapter.get_country_news",
                return_value=sample_news_items,
            ),
            patch(
                "app.news.business_news_service.qdrant_service.upsert_news_docs",
                side_effect=qdrant_error,
            ),
            patch(
                "app.news.business_news_service._get_redis",
                side_effect=Exception("No Redis in test"),
            ),
        ):
            with pytest.raises(Exception):
                _fetch_and_store_impl("US", force=True, db=spy_db)


# ─── Test Class 2: Kafka consumer.commit() Not Called on Failure ──────────────


class TestKafkaConsumerCommitNotCalledOnFailure:
    """
    Verifies that when news processing fails, consumer.commit() is NOT called.

    Current behaviour (BUG):
      1. _handle() wraps all logic in a broad try/except and never re-raises.
         A Qdrant failure is caught, logged, and _handle() returns normally.
      2. start_consumer() calls `await consumer.commit()` unconditionally after
         `await _handle(msg)` because _handle() appears to succeed.
      Result: failed Kafka messages are permanently acknowledged and never retried.
    """

    @pytest.mark.asyncio
    async def test_should_not_commit_kafka_offset_when_qdrant_upsert_fails(
        self, news_refresh_kafka_message
    ):
        """
        Assert 2: consumer.commit() must NOT be called when Qdrant upsert fails.

        RED: FAILS because:
          • _handle() catches ALL exceptions (broad try/except), never re-raises.
          • start_consumer() therefore cannot detect the failure and calls
            consumer.commit() unconditionally for every processed message.

        Fix (green phase):
          1. _handle() must re-raise (or signal) on processing failure.
          2. start_consumer() must gate consumer.commit() on _handle() succeeding.
        """
        from app.news.kafka_consumer import start_consumer

        mock_consumer = MagicMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.commit = AsyncMock()
        # Make `async for msg in consumer:` yield exactly one message
        # MagicMock's __aiter__ wraps a plain list in its own async iterator
        mock_consumer.__aiter__.return_value = [news_refresh_kafka_message]

        with (
            patch(
                "app.news.kafka_consumer.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "app.news.kafka_consumer.fetch_and_store_news",
                side_effect=Exception(
                    "Qdrant connection refused: upsert failed"
                ),
            ),
            patch(
                "app.news.kafka_consumer.publish_result",
                new_callable=AsyncMock,
            ),
        ):
            await start_consumer()

        mock_consumer.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_should_raise_when_news_processing_fails(
        self, news_refresh_kafka_message
    ):
        """
        _handle() must re-raise exceptions from fetch_and_store_news so that
        start_consumer() can detect the failure and skip consumer.commit().

        RED: FAILS because _handle() has a catch-all `except Exception` block
        that logs the error and returns normally, making failure invisible to
        start_consumer() and causing unconditional Kafka offset commits.
        """
        from app.news import kafka_consumer

        with (
            patch(
                "app.news.kafka_consumer.fetch_and_store_news",
                side_effect=Exception("Qdrant: upsert failed — service down"),
            ),
            patch(
                "app.news.kafka_consumer.publish_result",
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(Exception, match="Qdrant"):
                await kafka_consumer._handle(news_refresh_kafka_message)
