from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.config import settings

_model: TextCrossEncoder | None = None
RERANK_MODEL = "BAAI/bge-reranker-base"


def _get_model() -> TextCrossEncoder | None:
    if settings.app_env == "local":
        return None
    global _model
    if _model is None:
        _model = TextCrossEncoder(RERANK_MODEL)
    return _model


def rerank(query: str, items: list[dict], top_k: int = 3) -> list[dict]:
    if not items:
        return []
    model = _get_model()
    if model is None:
        return items[:top_k]
    docs = [f"{it.get('title', '')}\n{it.get('description', '')}" for it in items]
    scores = list(model.rerank(query, docs))
    scored = sorted(zip(scores, items), key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]
