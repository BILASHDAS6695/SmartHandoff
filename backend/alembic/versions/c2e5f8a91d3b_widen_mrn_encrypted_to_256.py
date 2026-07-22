"""Widen patient.mrn_encrypted column from VARCHAR(128) to VARCHAR(256).

Revision ID: c2e5f8a91d3b
Revises: b7d1c4a82e59
Create Date: 2026-07-21

US-007 (TASK-005 / GAP-2): The DeterministicEncryptedString TypeDecorator was
specified with length=256 throughout the task spec and the TASK-008 security
review checklist. The initial migration (a3f9e2c10b4d) created this column as
VARCHAR(128), which is insufficient per the spec requirement.

VARCHAR(256) accommodates AES-256-GCM encrypted MRNs of up to ~170 plaintext
characters:
    ceil((12_nonce + plaintext_bytes + 16_tag) / 3) * 4 ≤ 256
    → plaintext_bytes ≤ ~172 bytes

This migration widens the column in-place — no data rewrite is needed because
PostgreSQL can extend VARCHAR length without touching stored values.

Safe to run online: ALTER TYPE on VARCHAR(n) is a metadata-only change in
PostgreSQL (no table rewrite, no lock beyond an AccessShareLock).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e5f8a91d3b"
down_revision: Union[str, None] = "b7d1c4a82e59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen mrn_encrypted from VARCHAR(128) → VARCHAR(256).
    # PostgreSQL does not rewrite the table for VARCHAR length increases — this
    # is a catalog-only operation and executes without full table lock.
    op.alter_column(
        "patient",
        "mrn_encrypted",
        type_=sa.String(256),
        existing_nullable=False,
        existing_comment="Deterministically encrypted MRN for unique indexing (DR-020)",
    )


def downgrade() -> None:
    # Shrink mrn_encrypted back to VARCHAR(128).
    # WARNING: will fail if any stored ciphertext exceeds 128 characters.
    op.alter_column(
        "patient",
        "mrn_encrypted",
        type_=sa.String(128),
        existing_nullable=False,
        existing_comment="Deterministically encrypted MRN for unique indexing (DR-020)",
    )
