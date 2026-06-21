import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.news import embedder, reranker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI PID=%s started", os.getpid())
    # Pre-load ML models so first request is fast
    logger.info("Pre-loading embedding model (%s, app_env=%s)...", embedder._model_name(), settings.app_env)
    embedder._get_model()
    if settings.app_env == "local":
        logger.info("Local env: skipping reranker pre-load.")
    else:
        logger.info("Pre-loading reranker model...")
        reranker._get_model()
    logger.info("Models ready.")

    # Start gRPC server alongside uvicorn
    from app.grpc_server import serve as grpc_serve
    grpc_task = asyncio.create_task(grpc_serve())

    # Start Kafka consumer for news refresh requests
    from app.news.kafka_consumer import start_consumer
    kafka_task = asyncio.create_task(start_consumer())

    yield

    # Graceful shutdown
    kafka_task.cancel()
    grpc_task.cancel()
    await asyncio.gather(kafka_task, grpc_task, return_exceptions=True)

    from app.news.kafka_producer import stop_producer
    await stop_producer()


app = FastAPI(
    title="Hackonomics AI Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


from app.news.routes import router as news_router
from app.user_calendar.routes import router as calendar_router

app.include_router(news_router)
app.include_router(calendar_router)
