"""baseline_10_tables

Revision ID: 44dd5e80d058
Revises: None
Create Date: 2026-09-09 05:10:23.834546

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '44dd5e80d058'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from quantizedalert.store import SCHEMA
    for stmt in SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(sa.text(stmt))


def downgrade() -> None:
    tables = [
        "drift", "data_health", "usage", "customers", "deployments",
        "daily_runs", "alerts", "jobs", "predictions", "models",
    ]
    conn = op.get_bind()
    for t in tables:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {t}"))
