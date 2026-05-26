"""Add missing indexes for sessions and chat_history

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-26 00:00:00.000000

Adds:
- sessions.user_id        (session revocation on user deactivation)
- sessions.expires_at     (hourly expired-session cleanup)
- chat_history(user_id, instance_id)  (composite — all history queries filter on both)
- chat_history.created_at (ORDER BY in history listing)

Note: audit_log indexes (user_id, action, created_at) were already
created in migration 0002 and are not repeated here.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("idx_chat_history_user_instance", "chat_history", ["user_id", "instance_id"])
    op.create_index("idx_chat_history_created_at", "chat_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_chat_history_created_at", "chat_history")
    op.drop_index("idx_chat_history_user_instance", "chat_history")
    op.drop_index("ix_sessions_expires_at", "sessions")
    op.drop_index("ix_sessions_user_id", "sessions")
