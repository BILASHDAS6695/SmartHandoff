"""End-to-end test: create encounter → tasks execute → statuses complete."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import jwt

SECRET = "local-dev-jwt-secret-key-change-this-in-production"
ALG = "HS256"
BASE = "http://localhost:8000/api/v1"


def admin_token():
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "dev@smarthandoff.local",
            "user_id": str(uuid.uuid4()),
            "role": "ADMIN",
            "permissions": {"*": ["*"]},
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        SECRET,
        algorithm=ALG,
    )


async def main():
    headers = {"Authorization": f"Bearer {admin_token()}"}
    transport = httpx.AsyncHTTPTransport(proxy=None)
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30.0, transport=transport) as c:
        r = await c.get("/patients")
        print("patients status:", r.status_code)
        if r.status_code != 200:
            print(r.text[:500])
            return

        patients = r.json().get("patients", [])
        print(f"found {len(patients)} patients")
        if not patients:
            return

        patient = patients[0]
        print("patient id:", patient.get("id"))

        body = {
            "patient_id": patient["id"],
            "status": "ADMITTED",
            "unit": "ICU",
            "risk_tier": "MEDIUM",
            "event_type": "A01",
        }
        r = await c.post("/encounters", json=body)
        print("create encounter status:", r.status_code)
        if r.status_code != 200:
            print(r.text[:500])
            return
        enc = r.json()
        print("encounter id:", enc.get("id"))

        for i in range(12):
            await asyncio.sleep(1)
            r = await c.get(f"/tasks?encounter_id={enc['id']}")
            if r.status_code == 200:
                tasks = r.json()
                print(f"poll {i + 1}: tasks={len(tasks)}")
                for t in tasks:
                    print(f"  {t['agent_type']}: {t['status']}")
            else:
                print(f"poll {i + 1}: status {r.status_code}")


if __name__ == "__main__":
    asyncio.run(main())
