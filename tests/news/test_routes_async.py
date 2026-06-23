"""
Fix 1-C [HIGH]: chat_stream route must be async def to avoid anyio thread pool exhaustion.

The route calls llm_news_service.ask() which takes 2-6s (Qdrant + ML + Groq).
With sync def, FastAPI puts it in anyio's thread pool (default capacity: 40).
At 10 concurrent requests × 6s each = pool saturates under moderate load.

RED: fails because chat_stream is currently a sync `def`.
GREEN: passes once converted to `async def` with run_in_executor.
"""
import inspect

from app.news import routes


def test_chat_stream_route_should_be_async_function():
    """
    chat_stream must be an async def to avoid anyio thread pool exhaustion.

    RED: fails because the current route is `def chat_stream(...)`.
    GREEN: passes once changed to `async def chat_stream(...)`.
    """
    handler = routes.chat_stream

    assert inspect.iscoroutinefunction(handler), (
        f"routes.chat_stream must be 'async def' to prevent anyio thread pool exhaustion. "
        f"Got: {type(handler).__name__} (sync function). "
        f"Fix: convert to async def and wrap llm_news_service.ask() with run_in_executor."
    )


def test_chat_stream_route_is_registered():
    """Sanity check: the chat_stream function exists on the router."""
    assert hasattr(routes, "chat_stream"), "chat_stream must exist in routes module"
    assert callable(routes.chat_stream)
