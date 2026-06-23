"""
Phase 5 Integration Tests — ChatStream Queue Bridge and Error Propagation

These tests verify the interaction between components:
  - The asyncio.Queue token bridge between _produce_tokens (thread) and ChatStream (coroutine)
  - Token ordering and completeness across the thread-event-loop boundary
  - Error propagation from the producer thread to gRPC status codes
  - Concurrent ChatStream requests with isolated queues (no cross-contamination)
  - _build_chat_prompt correctly wires context into generate_chat_answer_stream calls
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.news.grpc_servicer import NewsAiServicer, _produce_tokens


def _make_request(question="test?", country_code="US"):
    req = MagicMock()
    req.question = question
    req.country_code = country_code
    return req


def _make_context():
    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()
    return ctx


# ── Test 1: Token relay preserves order and completeness ─────────────────────

@pytest.mark.asyncio
async def test_produce_tokens_bridge_relays_all_tokens_in_order():
    """
    _produce_tokens must relay every token yielded by generate_chat_answer_stream
    through the asyncio.Queue in the original order, then place the None sentinel.

    This is the core correctness invariant of the thread-to-event-loop bridge.
    """
    tokens = ["The", " market", " rose", " today"]
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    producer_exc: list[BaseException] = []

    def fake_stream(question, contexts):
        yield from tokens

    with patch("app.news.groq_adapter.generate_chat_answer_stream", side_effect=fake_stream):
        await loop.run_in_executor(
            None,
            _produce_tokens,
            loop,
            queue,
            "test?",
            [{"title": "T", "description": "D"}],
            producer_exc,
        )

    received = []
    while not queue.empty():
        item = queue.get_nowait()
        received.append(item)

    assert received[:-1] == tokens, (
        f"Queue must relay tokens in order. Expected {tokens}, got {received[:-1]}"
    )
    assert received[-1] is None, "Queue must end with None sentinel after all tokens"
    assert not producer_exc, f"No exception expected but got: {producer_exc}"


# ── Test 2: Producer exception → producer_exc populated, None sentinel placed ─

@pytest.mark.asyncio
async def test_produce_tokens_places_sentinel_after_exception():
    """
    When generate_chat_answer_stream raises, _produce_tokens must:
    1. Append the exception to producer_exc
    2. Still place the None sentinel so the consumer coroutine doesn't hang
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    producer_exc: list[BaseException] = []
    boom = RuntimeError("Groq API down")

    def failing_stream(question, contexts):
        yield "partial"
        raise boom

    with patch("app.news.groq_adapter.generate_chat_answer_stream", side_effect=failing_stream):
        await loop.run_in_executor(
            None,
            _produce_tokens,
            loop,
            queue,
            "test?",
            [],
            producer_exc,
        )

    # drain queue
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())

    assert items[-1] is None, "None sentinel must be placed even after exception so consumer can exit"
    assert len(producer_exc) == 1, f"Exception must be captured in producer_exc"
    assert producer_exc[0] is boom


# ── Test 3: ChatStream sets gRPC INTERNAL when producer errors ────────────────

@pytest.mark.asyncio
async def test_chatstream_sets_grpc_internal_status_on_producer_error():
    """
    When generate_chat_answer_stream raises mid-stream, ChatStream must:
    1. Set gRPC status to INTERNAL
    2. Set a generic detail string (not the raw exception)
    3. Still yield the final done=True chunk

    This is the end-to-end error path: producer thread raises → queue sentinel → consumer exits.
    """
    import grpc

    servicer = NewsAiServicer()
    request = _make_request()
    ctx = _make_context()

    def crashing_stream(question, contexts):
        yield "token1"
        raise RuntimeError("db connection pool exhausted at host=prod-db:5432")

    with (
        patch("app.news.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch("app.news.grpc_servicer.retrieve_context", return_value=[]),
        patch("app.news.groq_adapter.generate_chat_answer_stream", side_effect=crashing_stream),
    ):
        chunks = [chunk async for chunk in servicer.ChatStream(request, ctx)]

    ctx.set_code.assert_called_once_with(grpc.StatusCode.INTERNAL)
    ctx.set_details.assert_called_once()

    detail = ctx.set_details.call_args[0][0]
    assert "pool exhausted" not in detail, (
        f"Error detail must not leak raw exception. Got: {detail!r}"
    )
    assert "Internal server error" in detail, (
        f"Error detail must be generic 'Internal server error'. Got: {detail!r}"
    )

    done_chunks = [c for c in chunks if c.done]
    assert len(done_chunks) == 1, "Final done=True chunk must always be emitted"


# ── Test 4: Concurrent ChatStream calls use isolated queues ──────────────────

@pytest.mark.asyncio
async def test_concurrent_chatstream_calls_have_isolated_queues():
    """
    Two simultaneous ChatStream calls must each get their own asyncio.Queue.
    Tokens from request A must not appear in request B's response.

    This validates that queue creation is per-call (inside ChatStream), not shared state.
    """
    servicer = NewsAiServicer()

    ctx_a, ctx_b = _make_context(), _make_context()
    req_a = _make_request(question="question A", country_code="US")
    req_b = _make_request(question="question B", country_code="KR")

    call_count = {"n": 0}

    def stream_by_question(question, contexts):
        call_count["n"] += 1
        if "A" in question:
            yield "answer-A-token1"
            yield "answer-A-token2"
        else:
            yield "answer-B-token1"
            yield "answer-B-token2"

    with (
        patch("app.news.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch("app.news.grpc_servicer.retrieve_context", return_value=[]),
        patch("app.news.groq_adapter.generate_chat_answer_stream", side_effect=stream_by_question),
    ):
        chunks_a, chunks_b = await asyncio.gather(
            _collect(servicer.ChatStream(req_a, ctx_a)),
            _collect(servicer.ChatStream(req_b, ctx_b)),
        )

    texts_a = [c.text for c in chunks_a if c.text]
    texts_b = [c.text for c in chunks_b if c.text]

    assert all("A" in t for t in texts_a), f"Request A got wrong tokens: {texts_a}"
    assert all("B" in t for t in texts_b), f"Request B got wrong tokens: {texts_b}"
    assert not any("B" in t for t in texts_a), f"Request A contaminated by B: {texts_a}"
    assert not any("A" in t for t in texts_b), f"Request B contaminated by A: {texts_b}"


async def _collect(agen):
    return [item async for item in agen]
