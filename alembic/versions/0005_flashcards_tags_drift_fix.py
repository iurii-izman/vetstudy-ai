"""fix flashcards tags schema drift

Revision ID: 0005_flashcards_tags_drift_fix
Revises: 0004_topics_chat_thread_unique
Create Date: 2026-05-02
"""

from alembic import op


revision = "0005_flashcards_tags_drift_fix"
down_revision = "0004_topics_chat_thread_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE flashcards ADD COLUMN IF NOT EXISTS tags text[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    pass
