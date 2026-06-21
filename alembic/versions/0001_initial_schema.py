"""Initial FastAPI schema — calendar and news tables

Revision ID: 0001
Revises:
Create Date: 2026-05-24

Uses IF NOT EXISTS throughout so the migration is safe when applied to a
database that was previously managed by Django migrations.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_calendar (
            id                 SERIAL PRIMARY KEY,
            calendar_id        UUID UNIQUE NOT NULL,
            ory_identity_id    VARCHAR(255) UNIQUE NOT NULL,
            provider           VARCHAR(50) NOT NULL DEFAULT 'LOCAL',
            google_calendar_id VARCHAR(255),
            access_token       TEXT,
            refresh_token      TEXT,
            created_at         TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_calendar_ory_identity_id "
        "ON user_calendar (ory_identity_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS calendar_category (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ory_identity_id VARCHAR(255) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            color           VARCHAR(50) NOT NULL DEFAULT '#3b82f6',
            created_at      TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_category_ory "
        "ON calendar_category (ory_identity_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS calendar_event (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ory_identity_id VARCHAR(255) NOT NULL,
            title           VARCHAR(255) NOT NULL,
            start_at        TIMESTAMPTZ NOT NULL,
            end_at          TIMESTAMPTZ NOT NULL,
            estimated_cost  NUMERIC(12, 2),
            created_at      TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_event_ory "
        "ON calendar_event (ory_identity_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS calendar_event_categories (
            calendarevent_id UUID REFERENCES calendar_event(id) ON DELETE CASCADE,
            category_id      UUID REFERENCES calendar_category(id) ON DELETE CASCADE,
            PRIMARY KEY (calendarevent_id, category_id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS news_task_state (
            id           SERIAL PRIMARY KEY,
            country_code VARCHAR(10) UNIQUE NOT NULL,
            last_run_at  TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_task_state_country "
        "ON news_task_state (country_code)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS business_news (
            id           SERIAL PRIMARY KEY,
            country_code VARCHAR(10) NOT NULL,
            content      JSON NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_news_country "
        "ON business_news (country_code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS business_news_country_created_idx "
        "ON business_news (country_code, created_at)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS business_news_doc (
            id           SERIAL PRIMARY KEY,
            country_code VARCHAR(10) NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT NOT NULL,
            url          TEXT,
            created_at   TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_news_doc_country "
        "ON business_news_doc (country_code)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calendar_event_categories")
    op.execute("DROP TABLE IF EXISTS calendar_event")
    op.execute("DROP TABLE IF EXISTS calendar_category")
    op.execute("DROP TABLE IF EXISTS user_calendar")
    op.execute("DROP TABLE IF EXISTS business_news_doc")
    op.execute("DROP TABLE IF EXISTS business_news")
    op.execute("DROP TABLE IF EXISTS news_task_state")
