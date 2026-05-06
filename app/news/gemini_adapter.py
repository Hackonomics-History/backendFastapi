import logging
import time

from google import genai

from app.common.json_utils import parse_news_json
from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_DELAY = 3

NEWS_PROMPT = """You are a senior financial analyst. Identify the 5 most impactful business news stories from the last 72 hours for {country_name}.

Return ONLY a JSON array (no markdown, no commentary):
[
  {{"title": "...", "description": "..."}},
  ...
]

Each item must have a short, factual title and a 2-3 sentence description covering the key financial impact."""

CHAT_PROMPT = """You are a knowledgeable financial assistant. Answer the user's question based on the provided news context.

Context:
{context_text}

Question: {question}

Provide a clear, concise answer based on the context above."""


def _country_name(code: str) -> str:
    try:
        from babel import Locale
        return Locale("en").territories.get(code.upper(), code)
    except Exception:
        return code


def get_country_news(country_code: str) -> list[dict]:
    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = NEWS_PROMPT.format(country_name=_country_name(country_code))
    delay = INITIAL_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            return parse_news_json(response.text)
        except Exception as exc:
            msg = str(exc)
            if attempt < MAX_RETRIES and any(code in msg for code in ("429", "503")):
                logger.warning("Gemini rate limit (%s), retrying in %ss", country_code, delay)
                time.sleep(delay)
                delay *= 2
                continue
            raise


def generate_chat_answer(question: str, contexts: list[dict]) -> str:
    context_text = "\n\n".join(
        f"Title: {c.get('title', '')}\nDescription: {c.get('description', '')}"
        for c in contexts
    )
    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = CHAT_PROMPT.format(context_text=context_text, question=question)
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    return response.text
