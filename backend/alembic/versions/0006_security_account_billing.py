"""security hardening: email verification and zero-credit signup

Revision ID: 0006_security_account_billing
Revises: 0005_generation_pipeline_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_security_account_billing"
down_revision = "0005_generation_pipeline_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Preserve existing customers' ability to sign in; only new registrations must verify.
    users = sa.table("users", sa.column("email_verified", sa.Boolean()))
    op.execute(users.update().values(email_verified=sa.true()))
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "credit_balance",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("0"),
        )

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_email_verification_tokens_user_id", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_column("users", "email_verified")
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "credit_balance",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("10"),
        )
