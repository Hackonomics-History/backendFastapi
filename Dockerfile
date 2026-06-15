FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

# Pre-bake fastembed models so container startup is fast
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding('BAAI/bge-small-en-v1.5')"

FROM python:3.11-slim

WORKDIR /app

# Generated proto stubs use bare imports (e.g. `from ai.v1 import ai_pb2`).
# Adding the gen directory to PYTHONPATH makes the proto root importable
# and ensures ai_pb2_grpc.py can resolve its own cross-stub import.
ENV PYTHONPATH=/app/app/gen

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000 50052

ENTRYPOINT ["./entrypoint.sh"]
