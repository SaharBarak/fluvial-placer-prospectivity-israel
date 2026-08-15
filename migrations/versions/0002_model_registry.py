"""Model registry: versioned scoring weights with human-gated activation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("version", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="scoring-weights"),
        sa.Column("weights", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="CANDIDATE"),
        sa.Column("metrics", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )
    # Seed the hand-set v1 weights as the ACTIVE baseline.
    op.execute(
        """
        INSERT INTO ops.model_registry
            (id, version, kind, weights, status, metrics, created_at, activated_at)
        VALUES
            (gen_random_uuid(), 'prospect-v1', 'scoring-weights',
             '{"SOURCE_SYSTEM": 0.40, "TRANSPORT": 0.25, "TRAP": 0.35}',
             'ACTIVE', '{"origin": "hand-set baseline"}', now(), now())
        """
    )


def downgrade() -> None:
    raise RuntimeError("forward-only migrations (PRD §23.5)")
