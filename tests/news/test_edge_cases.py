"""
Step 11 — Extended and Edge Case Tests

Covers boundary and stress conditions not addressed by unit or integration tests:
  - ChatStream with zero tokens from Groq (only done=True emitted)
  - _build_chat_prompt with empty context list
  - _build_chat_prompt with contexts missing title/description keys
  - generate_chat_answer_stream with all-empty delta.content (nothing yielded)
  - Groq timeout: read timeout attribute is a concrete float (not None or ∞)
  - ChatStream: context lookup failure sets INTERNAL status without leaking exc
"""
from unittest.mock import MagicMock, patch

import pytest

from app.news import groq_adapter
from app.news.grpc_servicer import NewsAiServicer
from app.news.groq_adapter import _build_chat_prompt


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


# ── Edge: zero tokens from Groq ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chatstream_with_zero_tokens_emits_only_done_chunk():
    """
    When generate_chat_answer_stream yields nothing (Groq returns empty response),
    ChatStream must still emit exactly one final chunk with done=True and no content.
    """
    servicer = NewsAiServicer()
    request = _make_request()
    ctx = _make_context()

    def empty_stream(question, contexts):
        return iter([])

    with (
        patch("app.news.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch("app.news.grpc_servicer.retrieve_context", return_value=[]),
        patch("app.news.groq_adapter.generate_chat_answer_stream", side_effect=empty_stream),
    ):
        chunks = [c async for c in servicer.ChatStream(request, ctx)]

    content_chunks = [c for c in chunks if c.text]
    done_chunks = [c for c in chunks if c.done]

    assert not content_chunks, f"No content chunks expected for empty stream, got: {content_chunks}"
    assert len(done_chunks) == 1, "Exactly one done=True chunk must be emitted"
    ctx.set_code.assert_not_called()


# ── Edge: _build_chat_prompt with empty context list ─────────────────────────

def test_build_chat_prompt_with_empty_contexts():
    """
    _build_chat_prompt must not raise when contexts is empty.
    The prompt's {context_text} placeholder will be filled with an empty string.
    """
    prompt = _build_chat_prompt("What happened?", [])
    assert "What happened?" in prompt
    assert "{context_text}" not in prompt, "Template placeholder must be resolved"
    assert "{question}" not in prompt, "Template placeholder must be resolved"


# ── Edge: _build_chat_prompt with missing keys ────────────────────────────────

def test_build_chat_prompt_with_partial_context_dicts():
    """
    Context dicts may be missing 'title' or 'description' keys.
    _build_chat_prompt must use get() with '' default and not raise.
    """
    contexts = [
        {"title": "Only title"},
        {"description": "Only description"},
        {},
    ]
    prompt = _build_chat_prompt("test?", contexts)
    assert "Only title" in prompt
    assert "Only description" in prompt
    assert "{" not in prompt.split("Question:")[0], "No unresolved placeholders in context section"


# ── Edge: generate_chat_answer_stream with all-empty delta.content ────────────

def test_generate_chat_answer_stream_yields_nothing_when_all_content_empty():
    """
    If every chunk has empty/None delta.content, the generator yields nothing.
    The caller (ChatStream) handles this as a zero-token stream.
    """
    def make_empty_chunk():
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = None
        return chunk

    mock_stream = iter([make_empty_chunk() for _ in range(5)])

    with patch.object(groq_adapter, "_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_stream
        tokens = list(groq_adapter.generate_chat_answer_stream("test?", []))

    assert tokens == [], f"Expected no tokens when all delta.content is None, got: {tokens}"


# ── Edge: context lookup failure does not leak exception string ───────────────

@pytest.mark.asyncio
async def test_chatstream_context_lookup_failure_uses_generic_detail():
    """
    When retrieve_context raises, ChatStream must set_details with a generic
    message — not str(exc) which may contain internal paths or credentials.
    """
    import grpc

    servicer = NewsAiServicer()
    ctx = _make_context()
    request = _make_request()

    sensitive = "postgresql://admin:s3cr3t@prod-db:5432/hackonomics — connection refused"

    with (
        patch("app.news.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch("app.news.grpc_servicer.retrieve_context", side_effect=RuntimeError(sensitive)),
    ):
        # ChatStream returns early (no generator body) — drain to trigger
        gen = servicer.ChatStream(request, ctx)
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)

    ctx.set_code.assert_called_once_with(grpc.StatusCode.INTERNAL)
    ctx.set_details.assert_called_once()
    detail = ctx.set_details.call_args[0][0]
    assert sensitive not in detail, (
        f"Context lookup error must not leak sensitive info. Got: {detail!r}"
    )
    assert "Internal server error" in detail


# ── Boundary: Groq client timeout is a concrete finite float ─────────────────

def test_groq_client_timeout_is_finite_positive_float():
    """
    The Groq client's read timeout must be a positive finite float, not None,
    not infinity, and not the SDK's default 600s which would allow indefinite hangs.
    """
    import math

    client = groq_adapter._client
    timeout = getattr(client, "timeout", None)
    read = getattr(timeout, "read", None)

    assert read is not None, "timeout.read must be set"
    assert isinstance(read, (int, float)), f"timeout.read must be numeric, got {type(read)}"
    assert not math.isinf(read), "timeout.read must be finite (not math.inf)"
    assert 0 < read <= 30, f"timeout.read must be in (0, 30], got {read}"
