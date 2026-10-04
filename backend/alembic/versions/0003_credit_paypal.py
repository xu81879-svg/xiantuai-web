"""credit packs and PayPal one-time orders

Revision ID: 0003_credit_paypal
Revises: 0002_templates_help
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0003_credit_paypal"
down_revision = "0002_templates_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("credit_balance", sa.Integer(), nullable=False, server_default="10"))
    op.create_table(
        "credit_plans",
        sa.Column("code", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("amount", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "credit_orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_code", sa.String(length=40), sa.ForeignKey("credit_plans.code"), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("provider_order_id", sa.String(length=100), unique=True, nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("amount", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_credit_orders_user_id", "credit_orders", ["user_id"])
    op.create_index("ix_credit_orders_plan_code", "credit_orders", ["plan_code"])
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("credit_orders.id", ondelete="SET NULL"), unique=True, nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])

    plans = sa.table(
        "credit_plans",
        sa.column("code", sa.String), sa.column("name", sa.String), sa.column("description", sa.String),
        sa.column("credits", sa.Integer), sa.column("amount", sa.String), sa.column("currency", sa.String),
        sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer), sa.column("created_at", sa.DateTime),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(plans, [
        {"code": "starter", "name": "尝鲜包", "description": "适合第一次体验，生成 20 张素材", "credits": 20, "amount": "5.00", "currency": "USD", "is_active": True, "sort_order": 10, "created_at": now},
        {"code": "pro", "name": "专业包", "description": "适合日常经营，生成 100 张素材", "credits": 100, "amount": "19.00", "currency": "USD", "is_active": True, "sort_order": 20, "created_at": now},
        {"code": "business", "name": "商家包", "description": "适合批量营销，生成 300 张素材", "credits": 300, "amount": "49.00", "currency": "USD", "is_active": True, "sort_order": 30, "created_at": now},
    ])
def downgrade() -> None:
    op.drop_index("ix_credit_transactions_user_id", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_index("ix_credit_orders_plan_code", table_name="credit_orders")
    op.drop_index("ix_credit_orders_user_id", table_name="credit_orders")
    op.drop_table("credit_orders")
    op.drop_table("credit_plans")
    op.drop_column("users", "credit_balance")
