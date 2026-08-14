"""Initial schema: raw/core/analytics/ops/audit + PostGIS extension.

Revision ID: 0001
Revises:
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

from goldflow.infrastructure.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("raw", "core", "analytics", "ops", "audit")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    raise RuntimeError("forward-only migrations (PRD §23.5)")
