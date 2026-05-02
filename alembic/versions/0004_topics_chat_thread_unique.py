"""fix topic thread uniqueness scope

Revision ID: 0004_topics_chat_thread_unique
Revises: 0003_multi_user
Create Date: 2026-05-02
"""

from alembic import op


revision = "0004_topics_chat_thread_unique"
down_revision = "0003_multi_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("topics_telegram_thread_id_key", "topics", type_="unique")
    op.create_index("uq_topics_chat_thread", "topics", ["telegram_chat_id", "telegram_thread_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_topics_chat_thread", table_name="topics")
    op.create_unique_constraint("topics_telegram_thread_id_key", "topics", ["telegram_thread_id"])
