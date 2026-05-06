from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.news.models import BusinessNews, BusinessNewsDoc, NewsTaskState


class NewsRepository:
    def __init__(self, db: Session):
        self.db = db

    def find_latest(self, country_code: str) -> BusinessNews | None:
        return (
            self.db.query(BusinessNews)
            .filter(BusinessNews.country_code == country_code)
            .order_by(BusinessNews.created_at.desc())
            .first()
        )

    def save(self, country_code: str, content: list, now: datetime) -> BusinessNews:
        latest = self.find_latest(country_code)
        if latest and latest.content == content:
            return latest
        news = BusinessNews(country_code=country_code, content=content, created_at=now)
        self.db.add(news)
        self.db.flush()
        return news

    def find_latest_content(self, country_code: str, limit: int = 10) -> list[dict]:
        latest = self.find_latest(country_code)
        if not latest:
            return []
        items = latest.content or []
        return items[:limit]

    def get_or_create_task_state(self, country_code: str) -> NewsTaskState:
        state = (
            self.db.query(NewsTaskState)
            .filter(NewsTaskState.country_code == country_code)
            .first()
        )
        if not state:
            state = NewsTaskState(country_code=country_code, last_run_at=None)
            self.db.add(state)
            self.db.flush()
        return state

    def lock_task_state_nowait(self, country_code: str) -> NewsTaskState | None:
        return (
            self.db.query(NewsTaskState)
            .filter(NewsTaskState.country_code == country_code)
            .with_for_update(nowait=True)
            .first()
        )

    def update_task_last_run(self, country_code: str, now: datetime) -> None:
        self.db.query(NewsTaskState).filter(
            NewsTaskState.country_code == country_code
        ).update({"last_run_at": now})

    def replace_news_docs(self, country_code: str, docs: list[dict], now: datetime) -> None:
        self.db.query(BusinessNewsDoc).filter(
            BusinessNewsDoc.country_code == country_code
        ).delete()
        for doc in docs:
            self.db.add(
                BusinessNewsDoc(
                    country_code=country_code,
                    title=doc.get("title", ""),
                    description=doc.get("description", ""),
                    url=doc.get("url"),
                    created_at=now,
                )
            )

    def keyword_search(self, country_code: str, query: str, limit: int = 10) -> list[dict]:
        sql = text(
            """
            SELECT title, description, url,
                   ts_rank(to_tsvector('english', title || ' ' || description),
                           plainto_tsquery('english', :q)) AS kw_rank
            FROM business_news_doc
            WHERE country_code = :cc
              AND to_tsvector('english', title || ' ' || description)
                  @@ plainto_tsquery('english', :q)
            ORDER BY kw_rank DESC
            LIMIT :lim
            """
        )
        rows = self.db.execute(sql, {"cc": country_code, "q": query, "lim": limit}).fetchall()
        return [
            {"title": r.title, "description": r.description, "url": r.url, "_kw_rank": float(r.kw_rank)}
            for r in rows
        ]
