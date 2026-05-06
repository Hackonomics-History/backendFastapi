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
    cleaned = clean_json_response(raw)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        raise ValueError("Expected JSON array")
    return validate_news_items(parsed)
