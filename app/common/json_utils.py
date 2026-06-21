import json
import re


def clean_json_response(text: str) -> str:
    text = text.strip()
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def validate_news_items(items: list) -> list[dict]:
    result = []
    for item in items:
        if isinstance(item, dict) and item.get("title") and item.get("description"):
            result.append({"title": str(item["title"]), "description": str(item["description"])})
    return result


def parse_news_json(raw: str) -> list[dict]:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("GROQ RAW RESPONSE=%s", raw)

    cleaned = clean_json_response(raw)
    parsed = json.loads(cleaned)
    logger.info("PARSED NEWS JSON type=%s", type(parsed).__name__)

    if isinstance(parsed, list):
        news_items = parsed
    elif isinstance(parsed, dict):
        news_items = (
            parsed.get("news")
            or parsed.get("items")
            or parsed.get("articles")
            or parsed.get("news_items")
            or []
        )
        if not isinstance(news_items, list):
            raise ValueError(f"Expected list under news key, got {type(news_items).__name__}")
    else:
        raise ValueError(f"Unexpected JSON type: {type(parsed).__name__}")

    logger.info("PARSED NEWS COUNT=%d", len(news_items))
    return validate_news_items(news_items)
