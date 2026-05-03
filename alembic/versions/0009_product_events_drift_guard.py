"""repair product_events schema drift

Revision ID: 0009_product_events_drift_guard
Revises: 0008_product_analytics
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_product_events_drift_guard"
down_revision = "0008_product_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("product_events"):
        op.create_table(
            "product_events",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic_id", sa.UUID(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
            sa.Column("session_id", sa.UUID(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_name", sa.String(length=64), nullable=False),
            sa.Column("properties", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        inspector = sa.inspect(bind)

    existing_indexes = {row["name"] for row in inspector.get_indexes("product_events")}
    if "ix_product_events_user_created" not in existing_indexes:
        op.create_index("ix_product_events_user_created", "product_events", ["user_id", "created_at"], unique=False)
    if "ix_product_events_name_created" not in existing_indexes:
        op.create_index("ix_product_events_name_created", "product_events", ["event_name", "created_at"], unique=False)


def downgrade() -> None:
    pass
