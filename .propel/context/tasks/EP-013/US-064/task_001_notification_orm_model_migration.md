---
id: TASK-001
title: "Create `notification-service/app/models/notification.py` — Notification ORM Model + Alembic Migration"
user_story: US-064
epic: EP-013
sprint: 2
layer: Backend / Database
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-006]
---

# TASK-001: Create `notification-service/app/models/notification.py` — Notification ORM Model + Alembic Migration

> **Story:** US-064 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-064 DoD specifies:

> *"`notification` ORM table: `idempotency_key` (unique), `type`, `status`, `twilio_message_sid`, `sendgrid_message_id`, `phone_or_email`"*
> *"Idempotency check: `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`"*

This task defines the `Notification` SQLAlchemy 2.x ORM model for the `notification-service` Cloud Run service and authors the corresponding Alembic migration. The model is the single source of truth for idempotency enforcement, delivery status tracking, and Twilio/SendGrid message correlation.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `idempotency_key` carries `unique=True` + DB-level `UniqueConstraint` | DB-enforced uniqueness is the last line of defence against concurrent duplicate inserts (AC Scenario 2) |
| `status` as `Enum` (`PENDING`, `SENT`, `DELIVERED`, `FAILED`, `OPTED_OUT`) | Enum prevents free-text status values; aligns with US-067 DoD delivery status enumeration |
| `type` as `Enum` (`SMS`, `EMAIL`) | Matches Pub/Sub message schema field `type` (US-064 Technical Notes) |
| `phone_or_email` is nullable | Not all notifications carry both; nullable avoids placeholder values |
| `EncryptedString` for `phone_or_email` | PHI (phone/email) must be encrypted at rest per ADR-007; field-level AES-256-GCM |
| `recipient_id` UUID FK to `patient.id` | Links notification to patient for opt-out and audit log queries (US-067) |
| Separate `notification-service/` path (not `backend/`) | `NotificationService` is a standalone Cloud Run service per design.md §3.1 component inventory |

Design refs: ADR-007, US-064 DoD, US-067 DoD, design.md §3.1.

---

## Acceptance Criteria Addressed

| US-064 AC | Requirement |
|---|---|
| **Scenario 2** | `idempotency_key` unique constraint enables `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` |
| **Scenario 1** | `notification.status=SENT` and `twilio_message_sid` stored after successful SMS dispatch |
| **Scenario 3** | `notification.status` updates to `DELIVERED` via Twilio webhook |
| **Scenario 4** | `notification.status=FAILED` set when all 3 retries exhausted |

---

## Implementation Steps

### 1. Scaffold directory structure

```
notification-service/
├── app/
│   ├── db/
│   │   ├── __init__.py
│   │   └── base.py             ← re-uses same pattern as backend/app/db/base.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── notification.py     ← THIS TASK
│   └── migrations/
│       ├── env.py
│       └── versions/
│           └── 0001_notification_table.py  ← THIS TASK
├── alembic.ini
└── requirements.txt
```

```bash
mkdir -p notification-service/app/db
mkdir -p notification-service/app/models
mkdir -p notification-service/app/migrations/versions
touch notification-service/app/db/__init__.py
touch notification-service/app/models/__init__.py
```

### 2. Create `notification-service/app/db/base.py`

```python
"""SQLAlchemy declarative base for notification-service ORM models.

Mirrors backend/app/db/base.py — each Cloud Run service owns its
own metadata to avoid cross-service schema coupling.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Notification-service declarative base."""
    pass
```

### 3. Create `notification-service/app/models/notification.py`

```python
"""Notification ORM model — tracks every SMS and email dispatch attempt.

DR-002 / ADR-007: `phone_or_email` is encrypted with AES-256-GCM via the
shared `EncryptedString` custom SQLAlchemy type. The raw value is never
stored in plaintext.

Idempotency strategy (US-064 AC Scenario 2):
    The `idempotency_key` column carries a UNIQUE constraint.
    The dispatcher uses:
        INSERT INTO notification ... ON CONFLICT (idempotency_key) DO NOTHING
    to guarantee at-most-once dispatch even under Pub/Sub at-least-once delivery.

Delivery status lifecycle:
    PENDING → SENT (Twilio/SendGrid accepted)
             → DELIVERED (Twilio delivery webhook received)
             → FAILED (all 3 retry attempts exhausted)
    PENDING → OPTED_OUT (patient.notification_opt_out=True, non-urgent)

Design refs:
    US-064 DoD, US-067 DoD, ADR-007, design.md §3.1 (Notification Service component)
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.encryption import EncryptedString


class NotificationType(str, enum.Enum):
    """Notification channel type — matches Pub/Sub message schema `type` field."""

    SMS = "SMS"
    EMAIL = "EMAIL"


class NotificationStatus(str, enum.Enum):
    """Delivery lifecycle states.

    PENDING     — created, not yet dispatched.
    SENT        — Twilio/SendGrid accepted the request (2xx response).
    DELIVERED   — Twilio delivery webhook confirmed delivery.
    FAILED      — All retry attempts exhausted; CARE_TEAM_ALERT published.
    OPTED_OUT   — Patient opt-out suppressed dispatch (non-urgent only).
    """

    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    OPTED_OUT = "OPTED_OUT"


class Notification(Base):
    """One row per notification dispatch attempt.

    Idempotency is enforced at the DB level via the UNIQUE constraint on
    `idempotency_key`. The application layer uses
    ``INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`` so that
    Pub/Sub message redeliveries are safely ignored without a SELECT-first
    round-trip.
    """

    __tablename__ = "notification"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Surrogate PK — stable identifier for webhook correlation",
    )

    # -----------------------------------------------------------------------
    # Idempotency
    # -----------------------------------------------------------------------
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Caller-supplied idempotency key from Pub/Sub message (US-064 AC2)",
    )

    # -----------------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------------
    type: Mapped[NotificationType] = mapped_column(
        sa.Enum(NotificationType, name="notification_type"),
        nullable=False,
        comment="Dispatch channel: SMS or EMAIL",
    )

    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("patient.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to patient — used for opt-out check and audit correlation",
    )

    phone_or_email: Mapped[str | None] = mapped_column(
        EncryptedString(length=512),
        nullable=True,
        comment="AES-256-GCM encrypted recipient address (ADR-007 PHI field)",
    )

    template: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        comment="Template identifier, e.g. medication_reminder (Twilio) or d-xxx (SendGrid)",
    )

    substitutions: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        comment="Template variable substitution map from Pub/Sub message",
    )

    # -----------------------------------------------------------------------
    # Delivery status
    # -----------------------------------------------------------------------
    status: Mapped[NotificationStatus] = mapped_column(
        sa.Enum(NotificationStatus, name="notification_status"),
        nullable=False,
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
        index=True,
        comment="Delivery lifecycle state",
    )

    twilio_message_sid: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="Twilio MessageSid returned by messages.create(); used for webhook correlation",
    )

    sendgrid_message_id: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        comment="SendGrid X-Message-Id response header value",
    )

    retry_count: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of dispatch retry attempts completed",
    )

    last_error: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Last error message when status=FAILED",
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when Twilio/SendGrid accepted the request",
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="Timestamp from Twilio delivery webhook (AC Scenario 3)",
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        sa.UniqueConstraint("idempotency_key", name="uq_notification_idempotency_key"),
        sa.Index("ix_notification_recipient_status", "recipient_id", "status"),
        sa.Index("ix_notification_twilio_sid", "twilio_message_sid"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Notification id={self.id} type={self.type.value} "
            f"status={self.status.value} key={self.idempotency_key!r}>"
        )
```

### 4. Update `notification-service/app/models/__init__.py`

```python
from app.models.notification import Notification, NotificationStatus, NotificationType

__all__ = ["Notification", "NotificationStatus", "NotificationType"]
```

### 5. Author `notification-service/app/migrations/versions/0001_notification_table.py`

```python
"""Create notification table.

Revision ID: 0001
Revises:
Create Date: 2026-07-16

US-064: notification table for SMS/email dispatch tracking with
idempotency enforcement via UNIQUE constraint on idempotency_key.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "type",
            sa.Enum("SMS", "EMAIL", name="notification_type"),
            nullable=False,
        ),
        sa.Column("recipient_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_or_email", sa.String(512), nullable=True,
                  comment="AES-256-GCM encrypted (ADR-007)"),
        sa.Column("template", sa.String(128), nullable=False),
        sa.Column("substitutions", sa.JSON, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "SENT", "DELIVERED", "FAILED", "OPTED_OUT",
                name="notification_status",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("twilio_message_sid", sa.String(64), nullable=True),
        sa.Column("sendgrid_message_id", sa.String(128), nullable=True),
        sa.Column("retry_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_notification_idempotency_key", "notification", ["idempotency_key"]
    )
    op.create_index(
        "ix_notification_recipient_status", "notification", ["recipient_id", "status"]
    )
    op.create_index(
        "ix_notification_twilio_sid", "notification", ["twilio_message_sid"]
    )
    op.create_foreign_key(
        "fk_notification_patient",
        "notification",
        "patient",
        ["recipient_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_notification_patient", "notification", type_="foreignkey")
    op.drop_index("ix_notification_twilio_sid", table_name="notification")
    op.drop_index("ix_notification_recipient_status", table_name="notification")
    op.drop_constraint("uq_notification_idempotency_key", "notification", type_="unique")
    op.drop_table("notification")
    op.execute("DROP TYPE IF EXISTS notification_type")
    op.execute("DROP TYPE IF EXISTS notification_status")
```

---

## Validation

```bash
# Run alembic upgrade against a local/test PostgreSQL instance
cd notification-service
alembic upgrade head

# Verify unique constraint
psql -c "\d notification"
# Expected: idempotency_key has UNIQUE constraint and index

# Confirm enum types
psql -c "SELECT typname FROM pg_type WHERE typname IN ('notification_type','notification_status');"
# Expected: 2 rows
```

---

## Files Touched

| File | Action |
|------|--------|
| `notification-service/app/db/base.py` | Create |
| `notification-service/app/models/notification.py` | Create |
| `notification-service/app/models/__init__.py` | Create |
| `notification-service/app/migrations/versions/0001_notification_table.py` | Create |

---

## Definition of Done Checklist

- [ ] `notification` table has `idempotency_key` with `UNIQUE` constraint (`uq_notification_idempotency_key`)
- [ ] `status` column is `notification_status` Enum with all 5 states: `PENDING`, `SENT`, `DELIVERED`, `FAILED`, `OPTED_OUT`
- [ ] `phone_or_email` uses `EncryptedString` type (ADR-007 PHI protection)
- [ ] `twilio_message_sid` and `sendgrid_message_id` columns present
- [ ] `retry_count` column defaults to `0`
- [ ] Alembic migration upgrades and downgrades cleanly against a test DB
- [ ] `notification-service/app/models/__init__.py` exports `Notification`, `NotificationStatus`, `NotificationType`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-006 | Story | `patient` table must exist for FK; `notification_opt_out` column on `patient` |
| ADR-007 | Design | `EncryptedString` custom type from `backend/app/db/encryption.py` — copy or extract to shared lib |
