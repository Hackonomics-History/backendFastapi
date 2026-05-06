from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.config import settings
from app.news import embedder

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url)
    return _client


def _ensure_collection(dim: int) -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )


def upsert_news_docs(country_code: str, news_items: list[dict]) -> None:
    if not news_items:
        return
    texts = [f"{it['title']}\n{it.get('description', '')}" for it in news_items]
    vectors = embedder.embed_texts(texts)
    _ensure_collection(len(vectors[0]))

    points = []
    for item, vec in zip(news_items, vectors):
        url = item.get("url") or item.get("title", "")
        point_id = hash(url) & 0xFFFFFFFFFFFFFFFF
        points.append(
            PointStruct(
                id=point_id,
                vector=vec,
                payload={
                    "country_code": country_code,
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "url": item.get("url"),
                },
            )
        )
    get_client().upsert(collection_name=settings.qdrant_collection, points=points)


def vector_search(query: str, country_code: str, top_k: int = 10) -> list[dict]:
    vec = embedder.embed_text(query)
    _ensure_collection(len(vec))
    results = get_client().query_points(
        collection_name=settings.qdrant_collection,
        query=vec,
        query_filter=Filter(
            must=[FieldCondition(key="country_code", match=MatchValue(value=country_code))]
        ),
        limit=top_k,
    )
    return [
        {
            "title": r.payload.get("title", ""),
            "description": r.payload.get("description", ""),
            "url": r.payload.get("url"),
            "_vec_score": r.score,
        }
        for r in results.points
    ]
