import asyncio
import logging

import grpc

from app.config import settings

logger = logging.getLogger(__name__)


async def serve() -> None:
    from app.news.grpc_servicer import add_to_server as add_news
    from app.user_calendar.grpc_servicer import add_to_server as add_calendar

    server = grpc.aio.server()
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
