"""add_users_table

Revision ID: e70712906e52
Revises: 44dd5e80d058
Create Date: 2026-09-13 06:17:15.633729

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e70712906e52'
down_revision: str | Sequence[str] | None = '44dd5e80d058'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
    CREATE TABLE IF NOT EXISTS users (
      user_id TEXT PRIMARY KEY,
      clerk_id TEXT UNIQUE,
      email TEXT UNIQUE,
      telegram_chat_id TEXT UNIQUE,
      telegram_username TEXT,
      auth_provider TEXT DEFAULT 'clerk',
      plan TEXT DEFAULT 'free',
      status TEXT DEFAULT 'active',
      created_at TEXT,
      last_login_at TEXT
    );
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_users_clerk_id ON users(clerk_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users(telegram_chat_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS users;"))
