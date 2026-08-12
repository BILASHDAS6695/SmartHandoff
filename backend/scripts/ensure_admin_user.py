"""Ensure a Google-authenticated user has admin role in app_user.

Usage (from repo root, with DB env set):
    cd backend
    python -m scripts.ensure_admin_user balaganesh272@gmail.com

If the email already exists, update role to admin and activate.
If it does not exist, create a placeholder record using the email as idp_subject.
"""
from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import create_db_engines, dispose_db_engines, write_session_factory
from app.models.app_user import AppUser


async def ensure_admin(email: str) -> None:
    create_db_engines()
    assert write_session_factory is not None

    async with write_session_factory() as session:
        session: AsyncSession
        result = await session.execute(select(AppUser).where(AppUser.email == email))
        user = result.scalar_one_or_none()

        if user is not None:
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user.id)
                .values(role="admin", is_active=True)
            )
            await session.commit()
            print(f"Updated existing user {email} (id={user.id}) to role=admin, active=True")
        else:
            # Google sub is unknown until first login; use email as temporary placeholder.
            new_user = AppUser(
                id=uuid4(),
                idp_subject=email,
                email=email,
                full_name=email.split("@")[0],
                role="admin",
                is_active=True,
            )
            session.add(new_user)
            await session.commit()
            print(f"Created new admin user {email} (id={new_user.id})")
            print("NOTE: first Google login will overwrite idp_subject with Google's sub claim.")

    await dispose_db_engines()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.ensure_admin_user <email>")
        sys.exit(1)
    asyncio.run(ensure_admin(sys.argv[1].strip().lower()))
