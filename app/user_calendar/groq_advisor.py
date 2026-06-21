import logging

from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"

_client = Groq(api_key=settings.groq_api_key)

ADVISOR_PROMPT = """You are a financial calendar advisor helping users in {country_context}.

User's upcoming events:
{events_text}

The user has uploaded the following document:
{document_text}

Based on the document, suggest financial planning adjustments for the user's calendar events.

Return ONLY valid JSON (no markdown, no extra text) with this exact structure:
{{
  "advice": [
    {{
      "title": "Suggestion title",
      "description": "Detailed description",
      "event_ids": ["event-uuid-1"],
      "priority": "high|medium|low"
    }}
  ]
}}"""


def analyze_events_and_suggest(
    events_text: str,
    document_text: str,
    country_context: str,
) -> str:
    prompt = ADVISOR_PROMPT.format(
        country_context=country_context,
        events_text=events_text,
        document_text=document_text,
    )
    completion = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        stream=False,
    )

    logger.info("GROQ RAW RESPONSE = %s", completion.choices[0].message.content)
    return completion.choices[0].message.content
