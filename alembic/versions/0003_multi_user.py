"""multi-user hardening and admin entities

Revision ID: 0003_multi_user
Revises: 0002_indexes_seed
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_multi_user"
down_revision = "0002_indexes_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("specialization", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("onboarding_subjects", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"))
    op.add_column("users", sa.Column("quota_messages_per_day", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("users", sa.Column("quota_cost_per_month_usd", sa.Numeric(), nullable=False, server_default="25"))
    op.add_column("users", sa.Column("quota_premium_model_per_day", sa.Integer(), nullable=False, server_default="20"))
    op.add_column("users", sa.Column("billing_plan", sa.String(length=32), nullable=False, server_default="free"))
    op.add_column("users", sa.Column("billing_customer_ref", sa.String(length=128), nullable=True))
    op.execute("UPDATE users SET role = 'user' WHERE role NOT IN ('owner', 'admin', 'user')")
    op.alter_column("users", "role", existing_type=sa.String(length=64), type_=sa.String(length=16), existing_nullable=False, server_default="user")
    op.create_check_constraint("users_role_check", "users", "role in ('owner', 'admin', 'user')")

    op.add_column("topics", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_topics_user_id_users", "topics", "users", ["user_id"], ["id"])

    op.create_table(
        "usage_counters",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        sa.Column("period_key", sa.String(length=16), nullable=False),
        sa.Column("messages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("premium_messages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_usage_counters_user_period", "usage_counters", ["user_id", "period_type", "period_key"], unique=True)

    op.create_table(
        "error_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("error_events")
    op.drop_index("uq_usage_counters_user_period", table_name="usage_counters")
    op.drop_table("usage_counters")
    op.drop_constraint("fk_topics_user_id_users", "topics", type_="foreignkey")
    op.drop_column("topics", "user_id")
    op.drop_constraint("users_role_check", "users", type_="check")
    op.drop_column("users", "billing_customer_ref")
    op.drop_column("users", "billing_plan")
    op.drop_column("users", "quota_premium_model_per_day")
    op.drop_column("users", "quota_cost_per_month_usd")
    op.drop_column("users", "quota_messages_per_day")
    op.drop_column("users", "onboarding_subjects")
    op.drop_column("users", "onboarding_completed")
    op.drop_column("users", "specialization")
