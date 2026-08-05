#!/usr/bin/env python3
"""Test patient API endpoint directly using FastAPI test client."""
import asyncio
import sys
import os

# Set up environment - Ensure these are set via environment variables before running
# Do not store secrets in this file
os.environ.setdefault("PYTHONPATH", ".")
os.environ.setdefault("ALLOW_UNAUTHENTICATED_LOCALHOST", "true")
os.environ.setdefault("FHIR_BASE_URL", "https://r4.smarthealthit.org")

# Required env vars (must be set externally):
# PHI_ENCRYPTION_KEY
# PRIMARY_DATABASE_URL (format: postgresql+asyncpg://user:pass@host:port/dbname)
# REPLICA_DATABASE_URL
# OIDC_CLIENT_ID
# OAUTH_CLIENT_SECRET
# JWT_SIGNING_KEY

from fastapi.testclient import TestClient
from app.main import app
from app.core.auth.jwt import TokenClaims

print("=" * 80)
print("PATIENT API TEST - Direct FastAPI Call")
print("=" * 80)

# Create a test client
client = TestClient(app)

from app.core.auth.jwt import get_current_user

def override_auth():
    """Override with correct ADMIN role (uppercase)."""
    return TokenClaims(
        sub="test-user-123",
        role="ADMIN",  # ← UPPERCASE
        units=["ICU", "CCU", "MED"],
        email="test@example.com"
    )

app.dependency_overrides[get_current_user] = override_auth

print("\n1. Testing GET /api/v1/patients...")
try:
    response = client.get("/api/v1/patients?page=1&page_size=10")
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   [OK] Response format OK")
        print(f"   - Items returned: {len(data.get('items', []))}")
        print(f"   - Total count: {data.get('total')}")
        print(f"   - Page: {data.get('page')}")
        print(f"   - Page size: {data.get('page_size')}")
        
        if data.get('items'):
            first_patient = data['items'][0]
            print(f"\n   First patient details:")
            print(f"   - encounter_id: {first_patient.get('encounter_id')}")
            print(f"   - patient_id: {first_patient.get('patient_id')}")
            print(f"   - mrn_masked: {first_patient.get('mrn_masked')}")
            print(f"   - first_name: {first_patient.get('first_name')}")
            print(f"   - last_name: {first_patient.get('last_name')}")
            print(f"   - current_unit: {first_patient.get('current_unit')}")
            print(f"   - risk_tier: {first_patient.get('risk_tier')}")
            print(f"   - admission_date: {first_patient.get('admission_date')}")
    else:
        print(f"   [ERROR] Status code: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"   [ERROR] {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
