import json
import logging

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

ADVISOR_PROMPT = """You are a financial calendar advisor helping users in {country_context}.

User's upcoming events:
{events_text}

The user has uploaded the following document:
{document_text}

Based on the document, suggest financial planning adjustments for the user's calendar events.

Return ONLY a JSON array (no markdown):
[
  {{
    "title": "Suggestion title",
    "description": "Detailed description",
    "event_ids": ["event-uuid-1"],
    "priority": "high|medium|low"
  }}
]"""


def analyze_events_and_suggest(
    events_text: str,
    document_text: str,
    country_context: str,
) -> str:
    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = ADVISOR_PROMPT.format(
        country_context=country_context,
        events_text=events_text,
        document_text=document_text,
    )
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return response.text
