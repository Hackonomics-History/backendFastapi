"""
TDD Red Phase — gRPC Concurrency & Security Vulnerabilities
===========================================================

Three tests that MUST FAIL against the current implementation.

1. Event-loop blocking  (news/grpc_servicer.py, user_calendar/grpc_servicer.py)
   GenerateNews and GetAdvice are plain `def` on a grpc.aio server.
   grpc.aio calls sync handlers directly on the event-loop thread, blocking it
   while waiting for Groq HTTP / DB I/O. Both must become `async def`.

2. Timing-attack vulnerability  (grpc_server.py)
   _InternalTokenInterceptor compares the bearer token with `==`, creating a
   timing side-channel that leaks how many leading bytes matched. The comparison
   must use hmac.compare_digest.

3. Information disclosure  (news/grpc_servicer.py, user_calendar/grpc_servicer.py)
   Both servicers call context.set_details(str(exc)) on any exception, leaking
   internal DB URLs, file paths, and stack details to gRPC clients. Error detail
   must be a safe generic string.
"""

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import pytest


# ── Test 1: Event-loop blocking ───────────────────────────────────────────────

def test_generate_news_and_get_advice_must_be_coroutine_functions():
    """
    GenerateNews and GetAdvice must be `async def` coroutine functions so
    grpc.aio can await them without blocking the event loop.

    RED: fails because both methods are plain `def` (synchronous).
    GREEN: passes once both methods are changed to `async def` and use
           asyncio.to_thread / run_in_executor for blocking I/O.
    """
    from app.news.grpc_servicer import NewsAiServicer
    from app.user_calendar.grpc_servicer import CalendarAiServicer

    assert asyncio.iscoroutinefunction(NewsAiServicer.GenerateNews), (
        "NewsAiServicer.GenerateNews must be `async def` for grpc.aio compatibility. "
        "Sync methods run on the event-loop thread and block all other coroutines "
        "(Kafka consumer, gRPC accept loop) for the duration of the Groq HTTP call. "
        "Fix: change `def GenerateNews` to `async def GenerateNews` and offload "
        "blocking I/O with `await asyncio.to_thread(...)`."
    )

    assert asyncio.iscoroutinefunction(CalendarAiServicer.GetAdvice), (
        "CalendarAiServicer.GetAdvice must be `async def` for grpc.aio compatibility. "
        "Sync methods run on the event-loop thread and block all other coroutines "
        "for the duration of the blocking Groq HTTP call. "
        "Fix: change `def GetAdvice` to `async def GetAdvice` and offload "
        "blocking I/O with `await asyncio.to_thread(...)`."
    )


# ── Test 2: Timing-attack vulnerability ──────────────────────────────────────

def test_internal_token_interceptor_must_use_compare_digest():
    """
    _InternalTokenInterceptor must compare tokens with hmac.compare_digest
    instead of `==` to prevent timing side-channel attacks.

    A plain `==` comparison short-circuits on the first differing byte, leaking
    how many leading bytes of the real token an attacker has guessed. With
    enough requests the full token can be reconstructed byte-by-byte.

    RED: fails because grpc_server.py uses `==` for the token comparison.
    GREEN: passes once the comparison is changed to:
           `hmac.compare_digest(token, settings.ai_service_internal_token)`
    """
    from app.grpc_server import _InternalTokenInterceptor

    source = inspect.getsource(_InternalTokenInterceptor.intercept_service)

    assert "compare_digest" in source, (
        "_InternalTokenInterceptor.intercept_service uses plain `==` to compare "
        "x-internal-token, which is vulnerable to timing attacks. "
        "Fix: replace `metadata.get('x-internal-token') == settings.ai_service_internal_token` "
        "with `hmac.compare_digest(metadata.get('x-internal-token', ''), "
        "settings.ai_service_internal_token)`. "
        "Import hmac at the top of grpc_server.py."
    )


# ── Test 3: Information disclosure ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_news_must_not_leak_exception_details_to_grpc_client():
    """
    GenerateNews must NOT pass raw exception strings to context.set_details().
    Raw str(exc) often contains DB connection strings, file paths, or credentials
    (e.g. "postgresql://admin:secret@prod-db:5432/hackonomics") that become
    visible to any gRPC client receiving the error status.

    RED: fails because the current exception handler calls
         `context.set_details(str(exc))` unconditionally.
    GREEN: passes once the handler uses a safe generic message such as
           "Internal server error" instead of str(exc).
    """
    from app.news.grpc_servicer import NewsAiServicer

    sensitive_detail = "postgresql://admin:secret@prod-db:5432/hackonomics — connection refused"

    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()

    request = MagicMock()
    request.country_code = "US"
    request.force = False

    with (
        patch("app.news.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch(
            "app.news.grpc_servicer.fetch_and_store_news",
            side_effect=RuntimeError(sensitive_detail),
        ),
    ):
        await NewsAiServicer().GenerateNews(request, ctx)

    ctx.set_details.assert_called_once()
    leaked_detail: str = ctx.set_details.call_args[0][0]

    assert sensitive_detail not in leaked_detail, (
        f"GenerateNews leaked the raw exception to the gRPC client: {leaked_detail!r}. "
        "This exposes DB credentials and internal topology to callers. "
        "Fix: replace `context.set_details(str(exc))` with a generic message such as "
        "`context.set_details('Internal server error')` and log the full exception "
        "server-side with `logger.exception(...)`."
    )


@pytest.mark.asyncio
async def test_get_advice_must_not_leak_exception_details_to_grpc_client():
    """
    GetAdvice must NOT pass raw exception strings to context.set_details().
    Internal paths, credential fragments, or stack-trace snippets embedded in
    exception messages (e.g. "/secrets/groq_api_key: permission denied") must
    never reach gRPC callers.

    RED: fails because the current exception handler calls
         `context.set_details(str(exc))` unconditionally.
    GREEN: passes once the handler uses a safe generic message.
    """
    from app.user_calendar.grpc_servicer import CalendarAiServicer

    sensitive_detail = "/run/secrets/groq_api_key: permission denied — uid=1000"

    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()

    request = MagicMock()
    request.events_text = "Meeting 9am"
    request.document_text = ""
    request.country_context = "US"

    with (
        patch("app.user_calendar.grpc_servicer.SessionLocal", return_value=MagicMock()),
        patch(
            "app.user_calendar.grpc_servicer.groq_advisor.analyze_events_and_suggest",
            side_effect=PermissionError(sensitive_detail),
        ),
    ):
        await CalendarAiServicer().GetAdvice(request, ctx)

    ctx.set_details.assert_called_once()
    leaked_detail: str = ctx.set_details.call_args[0][0]

    assert sensitive_detail not in leaked_detail, (
        f"GetAdvice leaked the raw exception to the gRPC client: {leaked_detail!r}. "
        "This exposes internal secrets path and OS-level details to callers. "
        "Fix: replace `context.set_details(str(exc))` with a generic message such as "
        "`context.set_details('Internal server error')` and log with `logger.exception(...)`."
    )
