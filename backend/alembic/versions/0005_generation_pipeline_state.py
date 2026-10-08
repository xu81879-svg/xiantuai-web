"""Persist asynchronous generation pipeline state.

Revision ID: 0005_generation_pipeline_state
Revises: 0004_paypal_webhooks
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_generation_pipeline_state"
down_revision = "0004_paypal_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("pipeline_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("generations", "pipeline_state")
