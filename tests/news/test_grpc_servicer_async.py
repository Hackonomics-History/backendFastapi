"""
Fix 1-A [CRITICAL]: gRPC ChatStream must be an async generator to avoid blocking
the asyncio event loop.

RED: Both tests fail because ChatStream is currently a sync generator.
GREEN: Pass after converting to `async def ChatStream` + run_in_executor.
"""
import asyncio
import inspect
import time
from unittest.mock import MagicMock, patch

import pytest

from app.news.grpc_servicer import NewsAiServicer


def _make_request(question="What happened in markets?", country_code="US"):
    req = MagicMock()
    req.question = question
    req.country_code = country_code
    return req


def _make_context():
    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()
    return ctx


def _patch_servicer_deps(groq_delay: float = 0.0, groq_answer: str = "answer"):
    """Context manager that patches all external calls in the servicer."""
    import datetime

    mock_news = MagicMock()
    mock_news.content = [{"title": "T1", "description": "D1"}]
    mock_news.created_at = datetime.datetime.now(datetime.timezone.utc)

    def slow_groq(question, contexts):
        if groq_delay > 0:
            time.sleep(groq_delay)
        return groq_answer

    return (
        patch("app.news.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch("app.news.grpc_servicer.retrieve_context", return_value=[{"title": "T1", "description": "D1"}]),
        patch("app.news.groq_adapter.generate_chat_answer", side_effect=slow_groq),
    )


# ── Test 1: structural check ──────────────────────────────────────────────────

def test_chat_stream_should_be_async_generator():
    """
    ChatStream must return an async generator so grpc.aio server does not
    block the event loop. A sync generator causes 1-5s blackout for all
    other coroutines (Kafka consumer, gRPC accept loop).

    RED: fails because ChatStream is `def` (sync generator).
    """
    servicer = NewsAiServicer()
    request = _make_request()
    ctx = _make_context()

    patches = _patch_servicer_deps()
    with patches[0], patches[1], patches[2]:
        result = servicer.ChatStream(request, ctx)

    assert inspect.isasyncgen(result), (
        f"ChatStream must be an async generator for grpc.aio compatibility. "
        f"Got: {type(result).__name__}. "
        f"Fix: change `def ChatStream` to `async def ChatStream` and use run_in_executor."
    )


# ── Test 2: behavioral check — event loop must not be blocked ─────────────────

@pytest.mark.asyncio
async def test_chat_stream_should_not_block_event_loop():
    """
    While ChatStream awaits the Groq HTTP call, other coroutines must be
    scheduled (event loop not blocked).

    RED: fails because sync generator + time.sleep blocks the event loop,
         so the concurrent counter task cannot advance.
    GREEN: passes once ChatStream uses run_in_executor (Groq call in thread).
    """
    ticks: list[int] = []

    async def count_ticks():
        for i in range(30):
            await asyncio.sleep(0.01)  # 30 × 10ms = 300ms window
            ticks.append(i)

    servicer = NewsAiServicer()
    request = _make_request()
    ctx = _make_context()

    patches = _patch_servicer_deps(groq_delay=0.15)  # 150ms blocking Groq call

    with patches[0], patches[1], patches[2]:
        counter_task = asyncio.create_task(count_ticks())
        # Consume the stream (works only if ChatStream is async generator)
        async for _chunk in servicer.ChatStream(request, ctx):
            pass
        await counter_task

    assert len(ticks) >= 5, (
        f"Event loop was blocked during ChatStream: only {len(ticks)} ticks advanced "
        f"during 150ms Groq call. Expected ≥ 5 (event loop should be free). "
        f"Fix: use run_in_executor to offload blocking Groq HTTP call."
    )
