"""add previous_unit to encounter — US-015 A12 cancel-transfer revert

Adds a nullable ``previous_unit`` column to the ``encounter`` table.
The column stores the unit the patient occupied before a transfer (A02),
allowing ``CancellationService.handle_cancel_transfer()`` to restore the
encounter to its prior unit when an A12 Cancel Transfer event is received.

Revision ID: b8e2f5c93a17
Revises:     a1b2c3d4e5f6
Create Date: 2026-07-15 00:00:00.000000

Design refs:
    US-015  — A12: Cancel Transfer must revert unit to previous_unit
    FR-006  — Cancellation event handling
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "b8e2f5c93a17"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Add nullable ``previous_unit`` column to ``encounter``."""
    op.add_column(
        "encounter",
        sa.Column(
            "previous_unit",
            sa.String(length=64),
            nullable=True,
            comment=(
                "Unit occupied before the most recent A02 Transfer event. "
                "Populated by CancellationService (A12) to revert to prior unit."
            ),
        ),
    )


def downgrade() -> None:
    """Drop ``previous_unit`` column from ``encounter``."""
    op.drop_column("encounter", "previous_unit")
