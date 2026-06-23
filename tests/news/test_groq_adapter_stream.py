"""
Fix 1-B [CRITICAL]: Groq API must use streaming to yield tokens incrementally.
Fix 1-D [MEDIUM]:   Groq client must have a finite timeout (≤ 30s).

RED 1-B: fails because generate_chat_answer_stream() does not exist.
RED 1-D: fails because _client has default Groq SDK timeout (600s).
"""
from unittest.mock import MagicMock, patch

from app.news import groq_adapter


def _make_chunk(token: str):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = token if token else None
    return chunk


# ── Fix 1-B: streaming function must exist ────────────────────────────────────

def test_generate_chat_answer_stream_function_exists():
    """
    groq_adapter must expose generate_chat_answer_stream() for token-level streaming.

    RED: fails because only generate_chat_answer() exists (returns full string).
    GREEN: passes once generate_chat_answer_stream() is added.
    """
    assert hasattr(groq_adapter, "generate_chat_answer_stream"), (
        "groq_adapter.generate_chat_answer_stream() not found. "
        "Add a streaming variant that uses stream=True and yields tokens one by one. "
        "Current generate_chat_answer() buffers the full response (stream=False)."
    )


def test_generate_chat_answer_stream_yields_individual_tokens():
    """
    generate_chat_answer_stream must yield one string token at a time,
    not the full response as a single item.

    RED: fails because the function doesn't exist yet.
    GREEN: passes once streaming is implemented.
    """
    tokens = ["Hello", " world", " from", " Groq"]
    mock_stream = iter([_make_chunk(t) for t in tokens])

    with patch.object(groq_adapter, "_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_stream

        received = list(
            groq_adapter.generate_chat_answer_stream("What is the market trend?", [])
        )

    assert received == tokens, (
        f"Expected tokens {tokens}, got {received}. "
        "generate_chat_answer_stream must yield each token individually."
    )


def test_generate_chat_answer_stream_skips_empty_delta_content():
    """
    Empty delta.content (common in Groq streaming preamble) must be silently skipped.
    """
    tokens_with_empty = ["", "Hello", "", " world", ""]
    mock_stream = iter([_make_chunk(t) for t in tokens_with_empty])

    with patch.object(groq_adapter, "_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_stream

        received = list(
            groq_adapter.generate_chat_answer_stream("test", [])
        )

    assert received == ["Hello", " world"], (
        f"Expected ['Hello', ' world'], got {received}. "
        "Empty/None delta.content must be filtered out."
    )


def test_generate_chat_answer_stream_uses_stream_true():
    """
    generate_chat_answer_stream must call Groq API with stream=True.
    Calling with stream=False buffers the full response, defeating streaming.

    RED: fails because function doesn't exist yet.
    GREEN: passes once stream=True is used.
    """
    mock_stream = iter([])

    with patch.object(groq_adapter, "_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_stream

        list(groq_adapter.generate_chat_answer_stream("test", []))

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs is not None

    stream_kwarg = call_kwargs.kwargs.get("stream", call_kwargs[1].get("stream"))
    assert stream_kwarg is True, (
        f"Groq API must be called with stream=True for incremental token delivery. "
        f"Got stream={stream_kwarg}."
    )


# ── Fix 1-D: Groq client must have finite timeout ────────────────────────────

def test_groq_client_should_have_finite_read_timeout():
    """
    Groq client must be initialized with httpx.Timeout(30.0) or similar.
    Without a timeout, executor threads can hang indefinitely on Groq API delays.

    RED: fails because current _client = Groq(api_key=...) uses the SDK default
         timeout of 600s (too long to protect executor threads).
    GREEN: passes once _client = Groq(api_key=..., timeout=httpx.Timeout(30.0)).
    """
    client = groq_adapter._client
    timeout = getattr(client, "timeout", None)

    assert timeout is not None, (
        "Groq client must have timeout configured. "
        "Add: _client = Groq(api_key=..., timeout=httpx.Timeout(30.0))"
    )

    # httpx.Timeout stores read timeout in .read attribute
    read_timeout = getattr(timeout, "read", None)
    assert read_timeout is not None, (
        f"Groq client timeout.read must be set (not None). "
        f"Current timeout object: {timeout!r}"
    )
    assert read_timeout <= 30.0, (
        f"Groq read timeout is {read_timeout}s — too long. "
        f"Must be ≤ 30s to prevent executor threads from hanging. "
        f"Groq SDK default is 600s."
    )
