from fastembed import TextCrossEncoder

_model: TextCrossEncoder | None = None
RERANK_MODEL = "BAAI/bge-reranker-base"


def _get_model() -> TextCrossEncoder:
    global _model
    if _model is None:
        _model = TextCrossEncoder(RERANK_MODEL)
    return _model


def rerank(query: str, items: list[dict], top_k: int = 3) -> list[dict]:
    if not items:
        return []
    model = _get_model()
    docs = [f"{it.get('title', '')}\n{it.get('description', '')}" for it in items]
    scores = list(model.rerank(query, docs))
    scored = sorted(zip(scores, items), key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]
