import asyncio
import logging

import grpc

from app.config import settings

logger = logging.getLogger(__name__)


class _InternalTokenInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(self, continuation, handler_call_details):  # type: ignore[override]
        handler = await continuation(handler_call_details)
        if handler is None:
            return None

        metadata = dict(handler_call_details.invocation_metadata)
        if metadata.get("x-internal-token") == settings.internal_ai_token:
            return handler

        # Auth failed — return a handler that immediately aborts the call,
        # preserving the original serializers so framing is correct.
        if handler.response_streaming:
            async def abort_stream(_, context):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid internal token")
                return
                yield  # noqa: unreachable — required to declare this as an async generator

            return grpc.unary_stream_rpc_method_handler(
                abort_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        else:
            async def abort_unary(_, context):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid internal token")

            return grpc.unary_unary_rpc_method_handler(
                abort_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )


async def serve() -> None:
    from app.news.grpc_servicer import add_to_server as add_news
    from app.user_calendar.grpc_servicer import add_to_server as add_calendar

    server = grpc.aio.server(interceptors=[_InternalTokenInterceptor()])
    add_news(server)
    add_calendar(server)

    listen_addr = f"[::]:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)
    logger.info("gRPC server starting on %s", listen_addr)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        logger.info("gRPC server stopping...")
        await server.stop(grace=5)
