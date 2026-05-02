"""documents and rag tables

Revision ID: 0006_documents_rag
Revises: 0005_flashcards_tags_drift_fix
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0006_documents_rag"
down_revision = "0005_flashcards_tags_drift_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.UUID(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_user_topic_created", "documents", ["user_id", "topic_id", "created_at"])
    op.create_index("ix_documents_job_id", "documents", ["job_id"], unique=True)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.UUID(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source_message_id", sa.UUID(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("tags", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_chunks_document_idx", "document_chunks", ["document_id", "chunk_index"])
    op.create_index("ix_document_chunks_user_topic", "document_chunks", ["user_id", "topic_id"])
    op.create_index("ix_document_chunks_hash", "document_chunks", ["chunk_hash"])
    op.create_index("uq_document_chunks_doc_hash", "document_chunks", ["document_id", "chunk_hash"], unique=True)

    op.create_table(
        "source_citations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.UUID(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("message_id", sa.UUID(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("memory_item_id", sa.UUID(), sa.ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("document_chunk_id", sa.UUID(), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_citations_user_topic", "source_citations", ["user_id", "topic_id"])

    op.create_table(
        "review_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.UUID(), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("flashcard_id", sa.UUID(), sa.ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_events_user_topic", "review_events", ["user_id", "topic_id"])


def downgrade() -> None:
    op.drop_index("ix_review_events_user_topic", table_name="review_events")
    op.drop_table("review_events")
    op.drop_index("ix_source_citations_user_topic", table_name="source_citations")
    op.drop_table("source_citations")
    op.drop_index("uq_document_chunks_doc_hash", table_name="document_chunks")
    op.drop_index("ix_document_chunks_hash", table_name="document_chunks")
    op.drop_index("ix_document_chunks_user_topic", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_idx", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_job_id", table_name="documents")
    op.drop_index("ix_documents_user_topic_created", table_name="documents")
    op.drop_table("documents")
