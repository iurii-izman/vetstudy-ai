"""add product events table

Revision ID: 0008_product_analytics
Revises: 0007_learning_feedback
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_product_analytics"
down_revision = "0007_learning_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_events_user_created", "product_events", ["user_id", "created_at"], unique=False)
    op.create_index("ix_product_events_name_created", "product_events", ["event_name", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_events_name_created", table_name="product_events")
    op.drop_index("ix_product_events_user_created", table_name="product_events")
    op.drop_table("product_events")
