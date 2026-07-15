---
id: TASK-005
title: "Apply TypeDecorators to PHI Columns on ORM Models (Patient, Document, ChatbotTranscript)"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-003, TASK-004, US-006]
---

# TASK-005: Apply TypeDecorators to PHI Columns on ORM Models (Patient, Document, ChatbotTranscript)

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The TypeDecorators implemented in TASK-003 and TASK-004 are no-ops until they are applied to the ORM models that hold PHI. The US-006 tasks created the `Patient`, `Document`, and `ChatbotTranscript` models with `# TODO(US-007)` stubs in the encryption column mappings. This task removes those stubs and activates the real TypeDecorators.

### PHI columns requiring encryption (from DR-002)

| Model | Column | TypeDecorator | Notes |
|---|---|---|---|
| `Patient` | `first_name` | `EncryptedString(256)` | Non-deterministic |
| `Patient` | `last_name` | `EncryptedString(256)` | Non-deterministic |
| `Patient` | `date_of_birth` | `EncryptedString(32)` | Stored as ISO-8601 string: `"YYYY-MM-DD"` |
| `Patient` | `phone` | `EncryptedString(64)` | Non-deterministic |
| `Patient` | `email` | `EncryptedString(256)` | Non-deterministic |
| `Patient` | `mrn_encrypted` | `DeterministicEncryptedString(256)` | Deterministic; `unique=True` |
| `Document` | `content` | `EncryptedString(65535)` | DR-013; use `Text` impl (see Note) |
| `ChatbotTranscript` | `message_content` | `EncryptedString(65535)` | DR-016; use `Text` impl (see Note) |

> **Note on `Document.content` and `ChatbotTranscript.message_content`:** These fields hold multi-kilobyte text (discharge summaries, chat messages). AES-256-GCM encryption adds 28 bytes of overhead (12-byte nonce + 16-byte tag) plus ~33% base64 expansion. A 32KB document grows to ~44KB. `EncryptedString` uses `impl = String` (VARCHAR) by default, which has a length cap in PostgreSQL. For these columns, override `impl` to `Text` to avoid the 65535-character VARCHAR limit.

---

## Acceptance Criteria Addressed

| US-007 AC | Requirement |
|---|---|
| **Scenario 1** | PHI stored as ciphertext — TypeDecorators on Patient model encrypt before DB write |
| **Scenario 2** | PHI decrypts transparently on ORM access |
| **Scenario 3** | MRN unique constraint — `DeterministicEncryptedString` + `unique=True` on `mrn_encrypted` |
| **DoD** | PHI columns on `patient` and `encounter` tables use the appropriate TypeDecorators |

---

## Implementation Steps

### 1. Update `backend/app/models/patient.py`

Replace the `# TODO(US-007)` stubs with the real TypeDecorators. Only the column type declarations change — no business logic is modified.

```python
# backend/app/models/patient.py  (excerpt — show only changed columns)
from app.db.encryption import DeterministicEncryptedString, EncryptedString

class Patient(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "patient"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # ── Encrypted PHI fields (DR-002) ─────────────────────────────────────────
    # CHANGED: replaced String(256) stubs with EncryptedString TypeDecorators
    first_name: Mapped[str] = mapped_column(EncryptedString(256), nullable=False)
    last_name: Mapped[str] = mapped_column(EncryptedString(256), nullable=False)
    date_of_birth: Mapped[str] = mapped_column(EncryptedString(32), nullable=False)
    phone: Mapped[str | None] = mapped_column(EncryptedString(64), nullable=True)
    email: Mapped[str | None] = mapped_column(EncryptedString(256), nullable=True)

    # Deterministic encryption for MRN — enables UNIQUE index (DR-020)
    # CHANGED: replaced String(256) stub + TODO comment
    mrn_encrypted: Mapped[str] = mapped_column(
        DeterministicEncryptedString(256), nullable=False, unique=True
    )

    # ... (all other columns unchanged from US-006) ...
```

> **Important:** `date_of_birth` is typed `Mapped[str]` not `Mapped[date]`. The ORM stores the date as an ISO-8601 string (`"YYYY-MM-DD"`) before encryption. Application code calling `patient.date_of_birth` receives a string and must parse it if a `date` object is needed (`datetime.date.fromisoformat(patient.date_of_birth)`). This avoids SQLAlchemy type-coercion conflicts with the encrypted TypeDecorator.

### 2. Update `backend/app/models/document.py`

`Document.content` holds multi-kilobyte AI-generated text. Override `impl` to `Text`:

```python
# backend/app/models/document.py  (excerpt — show only changed column)
from sqlalchemy import Text
from app.db.encryption import EncryptedString


class EncryptedText(EncryptedString):
    """EncryptedString variant that uses PostgreSQL TEXT (no length cap)."""
    impl = Text


class Document(Base, TimestampMixin):
    __tablename__ = "document"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # CHANGED: replaced Text() stub with encrypted variant (DR-013)
    content: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)

    # ... (all other columns unchanged) ...
```

> **Note:** `EncryptedText` is a local subclass defined directly in `document.py` (or in `encryption.py` if reused elsewhere). It does not need to be added to `__all__` unless used outside of `document.py`.

### 3. Update `backend/app/models/chatbot_transcript.py`

Same pattern as `Document`:

```python
# backend/app/models/chatbot_transcript.py  (excerpt)
from sqlalchemy import Text
from app.db.encryption import EncryptedString


class EncryptedText(EncryptedString):
    impl = Text


class ChatbotTranscript(Base, TimestampMixin):
    __tablename__ = "chatbot_transcript"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # CHANGED: replaced Text() stub with encrypted variant (DR-016)
    message_content: Mapped[str] = mapped_column(EncryptedText(), nullable=False)

    # ... (all other columns unchanged) ...
```

> If `EncryptedText` is used in both `document.py` and `chatbot_transcript.py`, move it to `encryption.py` and add it to `__all__` to avoid duplication (DRY principle).

### 4. Verify No Alembic Migration is Required

The TypeDecorator swap (`String(256)` → `EncryptedString(256)`) does **not** change the underlying PostgreSQL column type — both map to `VARCHAR(256)`. Therefore, **no new Alembic migration is needed for this task**. Confirm with:

```bash
cd backend
alembic check
# Expected: "No new upgrade operations detected."
```

If `alembic check` reports new operations, investigate before proceeding — a migration was unexpectedly triggered.

### 5. Remove All `# TODO(US-007)` Comments

Search for any remaining TODO comments left by US-006:

```bash
grep -rn "TODO(US-007)" backend/app/
```

Expected output: **no matches** after this task is complete.

---

## Validation

Start the FastAPI application locally with a test PHI key and verify the Patient model encrypts/decrypts:

```bash
cd backend
export PHI_ENCRYPTION_KEY=$(python -c \
  "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
export DATABASE_URL="postgresql+asyncpg://smarthandoff:dev@localhost:5432/smarthandoff_dev"

python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.models.patient import Patient
from app.db.base import Base
from uuid import uuid4

engine = create_async_engine('$DATABASE_URL')

async def test():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession)
    async with async_session() as session:
        p = Patient(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            mrn_encrypted='MRN12345',
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)

    # Verify ORM returns plaintext
    assert p.first_name == 'John', f'Expected John, got {p.first_name}'
    assert p.mrn_encrypted == 'MRN12345'

    # Verify raw SQL returns ciphertext
    async with async_session() as session:
        result = await session.execute(
            text('SELECT first_name, mrn_encrypted FROM patient WHERE id = :id'),
            {'id': str(p.id)}
        )
        row = result.fetchone()
        assert row.first_name != 'John', 'first_name should be ciphertext in DB!'
        assert row.mrn_encrypted != 'MRN12345', 'mrn_encrypted should be ciphertext in DB!'
        print(f'Raw DB first_name: {row.first_name[:30]}...')
        print(f'Raw DB mrn_encrypted: {row.mrn_encrypted[:30]}...')

    print('PHI column encryption applied correctly')

asyncio.run(test())
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/models/patient.py` | Replace `# TODO(US-007)` stubs with `EncryptedString` / `DeterministicEncryptedString` column types |
| `backend/app/models/document.py` | Replace `content` column type with `EncryptedText` (Text-backed EncryptedString) |
| `backend/app/models/chatbot_transcript.py` | Replace `message_content` column type with `EncryptedText` |
| `backend/app/db/encryption.py` | Add `EncryptedText` subclass if shared across models |

---

## Definition of Done Checklist

- [ ] `Patient.first_name`, `last_name`, `date_of_birth`, `phone`, `email` use `EncryptedString`
- [ ] `Patient.mrn_encrypted` uses `DeterministicEncryptedString(256)` with `unique=True`
- [ ] `Document.content` uses `EncryptedText` (Text-backed EncryptedString)
- [ ] `ChatbotTranscript.message_content` uses `EncryptedText`
- [ ] `alembic check` reports no new migration operations (TypeDecorator swap is DDL-neutral)
- [ ] All `# TODO(US-007)` comments removed from `backend/app/`
- [ ] Raw SQL query on `patient` table returns ciphertext, not plaintext, for PHI columns
- [ ] ORM access to `patient.first_name` returns decrypted plaintext
