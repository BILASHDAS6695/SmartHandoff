# Findings Registry

## Findings

### 2026-08-13: Backend `.env` not loaded when starting uvicorn directly

**Symptom:**
Local `uvicorn app.main:app --reload` failed with:
- `PHI encryption key is not configured`
- `Database URL not configured: neither PRIMARY_DATABASE_URL nor PRIMARY_DB_SECRET_ID`

**Root cause:**
`python-dotenv` was available, but `load_dotenv()` was not invoked before app imports resolved settings. Exporting variables manually is fragile and the original `load_dotenv()` placement/path in `app/main.py` was incorrect.

**Fix:**
In `backend/app/main.py`, add a top-level `load_dotenv()` call using the path relative to `app/main.py` (`../.env`) before any FastAPI/app imports:

```python
import os
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"),
    override=False,
)
```

**Verification:**
- `curl -X POST http://localhost:8000/api/v1/auth/dev/test-token` returns 200.
- `curl -X POST http://localhost:8000/api/v1/signalr/negotiate -H "Authorization: Bearer <token>"` returns 200.

**Prevention:**
- Always start local backend from the `backend/` directory.
- Do not rely on manually exported env vars for local dev; rely on the committed `.env` loaded by the app.
