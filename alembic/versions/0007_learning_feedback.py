"""learning loop feedback and flashcard scheduling fields

Revision ID: 0007_learning_feedback
Revises: 0006_documents_rag
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_learning_feedback"
down_revision = "0006_documents_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flashcards", sa.Column("reps", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("flashcards", sa.Column("lapses", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("flashcards", sa.Column("difficulty", sa.Numeric(), nullable=True))
    op.add_column("flashcards", sa.Column("stability_days", sa.Numeric(), nullable=True))
    op.add_column("flashcards", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "feedback_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.UUID(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", sa.UUID(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_message_id", sa.UUID(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("feedback_type", sa.String(length=32), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_events_user_created", "feedback_events", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_events_user_created", table_name="feedback_events")
    op.drop_table("feedback_events")
    op.drop_column("flashcards", "last_reviewed_at")
    op.drop_column("flashcards", "stability_days")
    op.drop_column("flashcards", "difficulty")
    op.drop_column("flashcards", "lapses")
    op.drop_column("flashcards", "reps")
