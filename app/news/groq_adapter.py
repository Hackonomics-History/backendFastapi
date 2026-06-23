import logging
import time
from collections.abc import Iterator

import httpx
from groq import Groq

from app.common.json_utils import parse_news_json
from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_DELAY = 3
MODEL = "llama-3.3-70b-versatile"

_client = Groq(api_key=settings.groq_api_key, timeout=httpx.Timeout(30.0))

NEWS_PROMPT = """You are a senior financial analyst. Identify the 5 most impactful business news stories from the last 72 hours for {country_name}.

Return ONLY valid JSON (no markdown, no commentary) with this exact structure:
{{
  "news": [
    {{"title": "...", "description": "..."}},
    ...
  ]
}}

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


def _build_chat_prompt(question: str, contexts: list[dict]) -> str:
    context_text = "\n\n".join(
        f"Title: {c.get('title', '')}\nDescription: {c.get('description', '')}"
        for c in contexts
    )
    return CHAT_PROMPT.format(context_text=context_text, question=question)


def get_country_news(country_code: str) -> list[dict]:
    prompt = NEWS_PROMPT.format(country_name=_country_name(country_code))
    delay = INITIAL_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            completion = _client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                stream=False,
            )
            text = completion.choices[0].message.content
            logger.info("Groq response=%s", text)
            return parse_news_json(text)
        except Exception as exc:
            msg = str(exc)
            if attempt < MAX_RETRIES and any(code in msg for code in ("429", "503", "rate")):
                logger.warning("Groq rate limit (%s), retrying in %ss", country_code, delay)
                time.sleep(delay)
                delay *= 2
                continue
            raise


def generate_chat_answer(question: str, contexts: list[dict]) -> str:
    prompt = _build_chat_prompt(question, contexts)
    completion = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    return completion.choices[0].message.content


def generate_chat_answer_stream(question: str, contexts: list[dict]) -> Iterator[str]:
    """Yield Groq response tokens one at a time using server-sent streaming."""
    prompt = _build_chat_prompt(question, contexts)
    stream = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token
