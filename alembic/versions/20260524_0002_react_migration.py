"""React migration: new columns + AuditLog table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-24 00:00:00.000000

Adds:
- users.default_instance_id, users.preferences
- chat_history.response_metadata
- sessions.is_impersonation, sessions.impersonated_by_id
- audit_log table
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users: default_instance_id, preferences
    op.add_column("users", sa.Column("default_instance_id", sa.Integer(),
                  sa.ForeignKey("instances.id", ondelete="SET NULL"), nullable=True))
    op.add_column("users", sa.Column("preferences", sa.JSON(), nullable=True))

    # chat_history: response_metadata
    op.add_column("chat_history", sa.Column("response_metadata", sa.JSON(), nullable=True))

    # sessions: impersonation support
    op.add_column("sessions", sa.Column(
        "is_impersonation", sa.Boolean(), nullable=False, server_default=sa.false()
    ))
    op.add_column("sessions", sa.Column(
        "impersonated_by_id", sa.Integer(),
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    ))

    # audit_log table
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_created_at", "audit_log")
    op.drop_index("idx_audit_log_action", "audit_log")
    op.drop_index("idx_audit_log_user_id", "audit_log")
    op.drop_table("audit_log")

    op.drop_column("sessions", "impersonated_by_id")
    op.drop_column("sessions", "is_impersonation")
    op.drop_column("chat_history", "response_metadata")
    op.drop_column("users", "preferences")
    op.drop_column("users", "default_instance_id")
