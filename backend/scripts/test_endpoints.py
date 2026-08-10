"""Test new endpoints locally using FastAPI TestClient."""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["PRIMARY_DATABASE_URL"] = "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
os.environ["REPLICA_DATABASE_URL"] = "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
os.environ["PHI_ENCRYPTION_KEY"] = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
os.environ["JWT_SIGNING_KEY"] = "test-secret-key-minimum-32-characters-for-hs256-signing"
os.environ["ALLOW_UNAUTHENTICATED_LOCALHOST"] = "true"
os.environ["FHIR_BASE_URL"] = "https://r4.smarthealthit.org"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

encounter_id = "e9d6a8e1-0234-4a3b-bc39-b07d98008858"

token_resp = client.post(
    "/api/v1/auth/dev/test-token",
    json={"sub": "admin-user", "role": "ADMIN", "user_id": "00000000-0000-0000-0000-000000000001"},
)
print("Token status:", token_resp.status_code)
token = token_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("\n--- Medications ---")
meds = client.get(
    f"/api/v1/encounters/{encounter_id}/medications/reconciliation",
    headers=headers,
)
print("Status:", meds.status_code)
print(meds.text[:2000])

print("\n--- Documents ---")
docs = client.get(
    f"/api/v1/encounters/{encounter_id}/documents",
    headers=headers,
)
print("Status:", docs.status_code)
print(docs.text[:2000])
