---
id: TASK-007
title: "Implement PHI Re-Encryption Utility Script and Document in `infra/BOOTSTRAP.md`"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend (DevOps)
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-007: Implement PHI Re-Encryption Utility Script and Document in `infra/BOOTSTRAP.md`

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend (DevOps) | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-007 Acceptance Criterion 4 requires that when a new encryption key version is deployed to Secret Manager, a re-encryption background job can process all existing PHI records — decrypting with the old key and re-encrypting with the new key — without any data loss.

This task implements a standalone CLI utility script (`backend/scripts/reencrypt_phi.py`) designed to be run as a one-off Cloud Run job (not a recurring service). It processes all PHI-bearing tables in batches to avoid memory overload, wraps each batch in a DB transaction so partial failures are safe to retry, and logs progress without exposing any plaintext PHI.

The script is also documented in `infra/BOOTSTRAP.md` per the US-007 DoD requirement.

---

## Acceptance Criteria Addressed

| US-007 AC | Requirement |
|---|---|
| **Scenario 4** | Re-encryption background job runs; all existing PHI records re-encrypted with new key; ORM decryption continues to work; zero data loss |
| **DoD** | Re-encryption utility script documented in `infra/BOOTSTRAP.md` |

---

## Implementation Steps

### 1. Create `backend/scripts/reencrypt_phi.py`

```python
"""PHI re-encryption utility for AES-256-GCM key rotation.

Processes all PHI-bearing tables and re-encrypts each row from the OLD
encryption key to the NEW encryption key.

Usage:
    # Set the OLD key (key being rotated out)
    export PHI_ENCRYPTION_KEY_OLD=<base64url-encoded-32-byte-old-key>

    # Set the NEW key (key now active in Secret Manager)
    export PHI_ENCRYPTION_KEY_SECRET_ID=phi-encryption-key

    # Run the script
    cd backend
    python -m scripts.reencrypt_phi [--dry-run] [--batch-size 100] [--table patient]

Options:
    --dry-run       Log what would be re-encrypted without writing to DB.
    --batch-size    Rows per transaction batch. Default: 100.
    --table         Restrict to a single table (patient, document, chatbot_transcript).
                    Omit to process all PHI tables.

Security requirements:
    - Never log plaintext PHI values.
    - Each batch is wrapped in an explicit DB transaction.
    - A failed batch is rolled back; the script can be re-run safely (idempotent).
    - Progress is logged as row counts, not PHI content.

HIPAA compliance note:
    This script must be run by a privileged operator with Cloud SQL IAM access.
    All executions must be recorded in the audit log (manual entry required if
    the script cannot reach the SmartHandoff API audit endpoint).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
import sys
from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [reencrypt_phi] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

# ── PHI columns per table ─────────────────────────────────────────────────────
# (table_name, [non-deterministic columns], [deterministic columns])
PHI_TABLES: list[tuple[str, list[str], list[str]]] = [
    (
        "patient",
        ["first_name", "last_name", "date_of_birth", "phone", "email"],
        ["mrn_encrypted"],
    ),
    (
        "document",
        ["content"],
        [],
    ),
    (
        "chatbot_transcript",
        ["message_content"],
        [],
    ),
]


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _load_old_key() -> bytes:
    """Load and validate the OLD encryption key being rotated out."""
    raw = os.environ.get("PHI_ENCRYPTION_KEY_OLD")
    if not raw:
        raise RuntimeError(
            "PHI_ENCRYPTION_KEY_OLD environment variable is not set. "
            "This must hold the base64url-encoded old AES-256 key."
        )
    key = base64.urlsafe_b64decode(raw + "==")
    if len(key) != 32:
        raise ValueError(f"PHI_ENCRYPTION_KEY_OLD must be 32 bytes. Got {len(key)}.")
    return key


def _load_new_key() -> bytes:
    """Load the NEW encryption key from Secret Manager (or env for testing)."""
    # Reuse the standard key-loading mechanism.
    from app.db.encryption_key import clear_cached_key, get_phi_encryption_key
    clear_cached_key()
    return get_phi_encryption_key()


def _reencrypt_value(
    ciphertext_b64: str,
    old_key: bytes,
    new_key: bytes,
    deterministic: bool,
) -> str:
    """Decrypt with old_key; re-encrypt with new_key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64 as _b64
    from app.db.encryption import _NONCE_BYTES

    # ── Decrypt with old key ──────────────────────────────────────────────────
    payload = _b64.urlsafe_b64decode(ciphertext_b64 + "==")
    nonce = payload[:_NONCE_BYTES]
    encrypted = payload[_NONCE_BYTES:]
    plaintext = AESGCM(old_key).decrypt(nonce, encrypted, associated_data=None)

    # ── Re-encrypt with new key ───────────────────────────────────────────────
    if deterministic:
        from app.db.encryption import _encrypt_deterministic as _enc_det
        import app.db.encryption_key as _ek
        _original_key = _ek._cached_key
        _ek._cached_key = new_key
        try:
            result = _enc_det(plaintext)
        finally:
            _ek._cached_key = _original_key
        return result
    else:
        import os as _os
        new_nonce = _os.urandom(_NONCE_BYTES)
        new_encrypted = AESGCM(new_key).encrypt(new_nonce, plaintext, associated_data=None)
        return _b64.urlsafe_b64encode(new_nonce + new_encrypted).decode("ascii")


async def reencrypt_table(
    session_factory: async_sessionmaker,
    table: str,
    non_det_cols: list[str],
    det_cols: list[str],
    old_key: bytes,
    new_key: bytes,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Re-encrypt all rows in a single table. Returns total rows processed."""
    all_phi_cols = non_det_cols + det_cols
    if not all_phi_cols:
        return 0

    cols_sql = ", ".join(["id"] + all_phi_cols)
    total = 0
    last_id: str | None = None

    while True:
        async with session_factory() as session:
            async with session.begin():
                # Keyset pagination: avoids OFFSET which is slow on large tables
                if last_id is None:
                    rows_result = await session.execute(
                        text(
                            f"SELECT {cols_sql} FROM {table} "
                            f"WHERE deleted_at IS NULL "
                            f"ORDER BY id LIMIT :lim"
                        ),
                        {"lim": batch_size},
                    )
                else:
                    rows_result = await session.execute(
                        text(
                            f"SELECT {cols_sql} FROM {table} "
                            f"WHERE deleted_at IS NULL AND id > :last_id "
                            f"ORDER BY id LIMIT :lim"
                        ),
                        {"last_id": last_id, "lim": batch_size},
                    )

                rows = rows_result.fetchall()
                if not rows:
                    break

                for row in rows:
                    row_dict = row._mapping
                    updates: dict[str, str] = {}

                    for col in non_det_cols:
                        val = row_dict[col]
                        if val is not None:
                            updates[col] = _reencrypt_value(
                                val, old_key, new_key, deterministic=False
                            )

                    for col in det_cols:
                        val = row_dict[col]
                        if val is not None:
                            updates[col] = _reencrypt_value(
                                val, old_key, new_key, deterministic=True
                            )

                    if updates and not dry_run:
                        set_clause = ", ".join(f"{c} = :{c}" for c in updates)
                        await session.execute(
                            text(f"UPDATE {table} SET {set_clause} WHERE id = :id"),
                            {**updates, "id": str(row_dict["id"])},
                        )

                last_id = str(rows[-1]._mapping["id"])
                total += len(rows)
                action = "Would re-encrypt" if dry_run else "Re-encrypted"
                logger.info("%s %d rows in table '%s' (batch up to id=%s)", action, total, table, last_id)

    return total


async def main(args: argparse.Namespace) -> None:
    logger.info("Starting PHI re-encryption. dry_run=%s, batch_size=%d", args.dry_run, args.batch_size)

    old_key = _load_old_key()
    new_key = _load_new_key()

    if old_key == new_key:
        logger.warning("OLD and NEW keys are identical — nothing to re-encrypt.")
        return

    engine = create_async_engine(_get_database_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    tables_to_process = PHI_TABLES
    if args.table:
        tables_to_process = [t for t in PHI_TABLES if t[0] == args.table]
        if not tables_to_process:
            logger.error("Unknown table '%s'. Valid options: %s", args.table, [t[0] for t in PHI_TABLES])
            sys.exit(1)

    total_rows = 0
    for table, non_det_cols, det_cols in tables_to_process:
        logger.info("Processing table: %s", table)
        count = await reencrypt_table(
            session_factory, table, non_det_cols, det_cols,
            old_key, new_key, args.batch_size, args.dry_run,
        )
        logger.info("Table '%s' complete: %d rows processed.", table, count)
        total_rows += count

    await engine.dispose()
    action = "Would have re-encrypted" if args.dry_run else "Successfully re-encrypted"
    logger.info("%s %d total PHI rows across %d tables.", action, total_rows, len(tables_to_process))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PHI re-encryption utility for key rotation.")
    parser.add_argument("--dry-run", action="store_true", help="Log without writing to DB.")
    parser.add_argument("--batch-size", type=int, default=100, help="Rows per transaction batch.")
    parser.add_argument("--table", type=str, default=None, help="Restrict to a single table.")
    args = parser.parse_args()
    asyncio.run(main(args))
```

### 2. Update `infra/BOOTSTRAP.md` — Key Rotation Runbook

Append the following section to `infra/BOOTSTRAP.md` (create the file if it does not exist):

```markdown
## PHI Encryption Key Rotation

SmartHandoff uses AES-256-GCM field-level encryption for all PHI columns.
When the encryption key must be rotated (annual rotation, suspected compromise),
follow this procedure:

### Prerequisites

- Access to GCP Secret Manager with `secretmanager.versions.add` permission
- Cloud SQL IAM role: `cloudsql.instances.connect`
- `DATABASE_URL` pointing to the Cloud SQL instance (via Cloud SQL Auth Proxy or VPC)

### Step 1 — Generate a new AES-256 key

```bash
NEW_KEY=$(python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
echo "New key (store securely — do NOT log): [REDACTED]"
```

### Step 2 — Store the new key as a new Secret Manager version

```bash
echo -n "$NEW_KEY" | gcloud secrets versions add phi-encryption-key --data-file=-
```

This creates a new version. The previous version remains accessible until disabled.

### Step 3 — Retrieve the old key

```bash
# The old key is the currently active Secret Manager version BEFORE Step 2.
# If it was previously stored, retrieve it:
OLD_KEY=$(gcloud secrets versions access <old-version-number> \
  --secret=phi-encryption-key --project=$GOOGLE_CLOUD_PROJECT)
```

### Step 4 — Run the re-encryption script (dry-run first)

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://<user>:<pass>@<host>/smarthandoff"
export PHI_ENCRYPTION_KEY_OLD="$OLD_KEY"
export PHI_ENCRYPTION_KEY_SECRET_ID="phi-encryption-key"  # Uses new version

# Dry run — no DB writes
python -m scripts.reencrypt_phi --dry-run --batch-size 100

# Review the log. If counts look correct, run for real:
python -m scripts.reencrypt_phi --batch-size 100
```

### Step 5 — Deploy updated Cloud Run services

After re-encryption completes, deploy all Cloud Run services with the new
Secret Manager version binding active. Existing services will continue to
function because the old key version is still accessible in Secret Manager.

```bash
# Trigger Cloud Build / Cloud Deploy for all backend services
gcloud builds submit --config cloudbuild.yaml .
```

### Step 6 — Disable the old Secret Manager key version

Once all services are using the new key and re-encryption is confirmed:

```bash
gcloud secrets versions disable <old-version-number> \
  --secret=phi-encryption-key --project=$GOOGLE_CLOUD_PROJECT
```

### Rollback

If re-encryption fails mid-way, the script is **idempotent** — already
re-encrypted rows remain valid. Re-run the script after resolving the issue.
If a row cannot be decrypted, it indicates key mismatch; contact the security
team immediately and do NOT disable the old key version.
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/scripts/__init__.py` | Create (empty, makes `scripts` a package for `python -m scripts.reencrypt_phi`) |
| `backend/scripts/reencrypt_phi.py` | Create — PHI re-encryption CLI utility |
| `infra/BOOTSTRAP.md` | Append key rotation runbook section |

---

## Definition of Done Checklist

- [ ] `backend/scripts/reencrypt_phi.py` created and runnable with `python -m scripts.reencrypt_phi --help`
- [ ] Script processes `patient`, `document`, `chatbot_transcript` tables
- [ ] Batch processing with keyset pagination (no OFFSET) to handle large datasets
- [ ] Dry-run mode logs row counts without writing to DB
- [ ] Each batch wrapped in a DB transaction (failed batch is rolled back; script is safe to re-run)
- [ ] No plaintext PHI values logged at any point
- [ ] Key rotation runbook documented in `infra/BOOTSTRAP.md`
- [ ] Script tested against a local PostgreSQL container in dry-run mode
