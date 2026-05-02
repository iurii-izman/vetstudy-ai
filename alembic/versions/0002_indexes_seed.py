"""add indexes and seed subjects

Revision ID: 0002_indexes_seed
Revises: 0001_init
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers, used by Alembic.
revision = "0002_indexes_seed"
down_revision = "0001_init"
branch_labels = None
depends_on = None


SUBJECTS = [
    ("pharmacology", "Pharmacology", "Фокус на фармакологии, дозировках и противопоказаниях."),
    ("surgery", "Surgery", "Фокус на хирургической тактике и послеоперационном ведении."),
    ("internal_medicine", "Internal Medicine", "Фокус на внутренней медицине, диагностике и лечении."),
    ("anatomy", "Anatomy", "Фокус на анатомии и клинической применимости."),
    ("parasitology", "Parasitology", "Фокус на паразитологии и схемах терапии."),
    ("diagnostics", "Diagnostics", "Фокус на лабораторной и инструментальной диагностике."),
    ("clinical_cases", "Clinical Cases", "Фокус на разборе клинических кейсов и дифференциалах."),
    ("exam", "Exam", "Фокус на подготовке к экзамену и тестовым вопросам."),
    ("general", "General", "Общий режим консультации VetStudy AI."),
]


def upgrade() -> None:
    op.create_index("ix_topics_telegram_thread_id", "topics", ["telegram_thread_id"], unique=False)
    op.create_index(
        "uq_sessions_active_user_topic",
        "sessions",
        ["user_id", "topic_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index("ix_memory_items_user_topic_kind", "memory_items", ["user_id", "topic_id", "kind"], unique=False)
    op.create_index("ix_memory_items_tags", "memory_items", ["tags"], unique=False, postgresql_using="gin")

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regtype('vector') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS ix_memory_items_embedding_ivfflat
                ON memory_items USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            END IF;
        END
        $$;
        """
    )

    for slug, title, system_prompt in SUBJECTS:
        op.execute(
            sa.text(
                """
                INSERT INTO subjects (id, slug, title, system_prompt, created_at)
                VALUES (:id, :slug, :title, :system_prompt, now())
                ON CONFLICT (slug) DO NOTHING
                """
            ).bindparams(id=uuid.uuid4(), slug=slug, title=title, system_prompt=system_prompt)
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_items_embedding_ivfflat")
    op.drop_index("ix_memory_items_tags", table_name="memory_items")
    op.drop_index("ix_memory_items_user_topic_kind", table_name="memory_items")
    op.drop_index("uq_sessions_active_user_topic", table_name="sessions")
    op.drop_index("ix_topics_telegram_thread_id", table_name="topics")
