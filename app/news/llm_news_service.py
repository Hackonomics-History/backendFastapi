from sqlalchemy.orm import Session

from app.news import gemini_adapter
from app.news.hybrid_service import retrieve_context
from app.news.repository import NewsRepository


def ask(question: str, country_code: str, db: Session) -> dict:
    repo = NewsRepository(db)
    contexts = retrieve_context(question, country_code, repo)
    answer = gemini_adapter.generate_chat_answer(question, contexts)
    return {"answer": answer, "contexts": contexts}
