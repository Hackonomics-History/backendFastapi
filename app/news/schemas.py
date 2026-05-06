from datetime import datetime

from pydantic import BaseModel


class NewsItem(BaseModel):
    title: str
    description: str


class BusinessNewsResponse(BaseModel):
    country_code: str | None
    country_name: str | None
    news: list[NewsItem]
    last_updated: datetime | None
    next_update: datetime | None
    update_interval_hours: int


class NewsRefreshResponse(BaseModel):
    status: str
    country_code: str


class ChatRequest(BaseModel):
    question: str


class RerankItem(BaseModel):
    title: str
    description: str
    url: str | None = None
