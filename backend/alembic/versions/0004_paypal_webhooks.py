"""PayPal webhook idempotency

Revision ID: 0004_paypal_webhooks
Revises: 0003_credit_paypal
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_paypal_webhooks"
down_revision = "0003_credit_paypal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paypal_webhook_events",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("paypal_webhook_events")
