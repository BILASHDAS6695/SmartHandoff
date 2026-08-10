"""Local development authentication helpers."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.auth.jwt import create_access_token
from app.dependencies import get_current_user
from app.schemas.user import User as UserSchema

router = APIRouter()


class DevTestTokenRequest(BaseModel):
    email: str = "dev@example.com"
    role: str = "nurse"
    unit: str | None = "4-West"


@router.post("/test-token", response_model=dict)
def dev_test_token(payload: DevTestTokenRequest):
    if not settings.ALLOW_UNAUTHENTICATED_LOCALHOST:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev token endpoint is disabled",
        )

    access_token = create_access_token(
        data={
            "sub": payload.email,
            "email": payload.email,
            "role": payload.role.lower(),
            "unit": payload.unit,
        }
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": payload.role.lower(),
    }


@router.get("/me", response_model=UserSchema)
def dev_me(current_user: UserSchema = Depends(get_current_user)):
    return current_user
