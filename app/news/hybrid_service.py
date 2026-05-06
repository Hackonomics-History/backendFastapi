from app.news import qdrant_service, reranker
from app.news.repository import NewsRepository

ORDINAL_MAP = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}


def _rrf(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            key = item.get("title", "") + "|" + item.get("description", "")
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            items[key] = item
    return [items[k] for k in sorted(scores, key=lambda x: scores[x], reverse=True)]


def hybrid_search(question: str, country_code: str, repo: NewsRepository, top_k: int = 3) -> list[dict]:
    vec_results = qdrant_service.vector_search(question, country_code, top_k=10)
    kw_results = repo.keyword_search(country_code, question, limit=10)
    fused = _rrf([vec_results, kw_results])
    candidates = fused[:20]
    return reranker.rerank(question, candidates, top_k=top_k)


def retrieve_context(question: str, country_code: str, repo: NewsRepository) -> list[dict]:
    q_lower = question.lower()
    for ordinal, idx in ORDINAL_MAP.items():
        if ordinal in q_lower:
            news_content = repo.find_latest_content(country_code)
            if idx < len(news_content):
                item = news_content[idx]
                return [{"title": item.get("title", ""), "description": item.get("description", ""), "url": None}]
            break
    return hybrid_search(question, country_code, repo)
