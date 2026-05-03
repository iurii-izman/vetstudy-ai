"""add card_type and needs_manual_check to flashcard

Revision ID: 0010_flashcard_card_type_check
Revises: 0009_product_events_drift_guard
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_flashcard_card_type_check"
down_revision = "0009_product_events_drift_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('flashcards', sa.Column('card_type', sa.String(length=32), server_default='fact', nullable=False))
    op.add_column('flashcards', sa.Column('needs_manual_check', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('flashcards', 'needs_manual_check')
    op.drop_column('flashcards', 'card_type')
