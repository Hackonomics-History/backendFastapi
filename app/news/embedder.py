from fastembed import TextEmbedding

_model: TextEmbedding | None = None

_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(_MODEL_NAME)
    return _model

def _model_name() -> str:
    return _MODEL_NAME

def embed_text(text: str) -> list[float]:
    model = _get_model()
    return list(next(iter(model.embed([text]))))


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    return [list(v) for v in model.embed(texts)]