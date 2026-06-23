from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_embedder():
    """Patch embed_texts to return realistic-length vectors for each input text."""
    def _embed_texts(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]

    with patch("app.news.embedder.embed_texts", side_effect=_embed_texts):
        yield
