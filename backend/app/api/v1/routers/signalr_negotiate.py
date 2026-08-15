"""Router: POST /api/v1/signalr/negotiate

Negotiate endpoint for Azure SignalR Service.
Angular HubConnectionBuilder calls this before opening the WebSocket.

Flow:
  1. Validate staff JWT via get_current_user dependency.
  2. Extract unit_id, role, encounter_ids from token claims.
  3. Call GroupResolver to compute group list.
  4. Call Azure SignalR Management SDK (or REST API) to generate a client
     access token scoped to those groups.
  5. Return { url, accessToken } to Angular client.

Security (US-022 Scenario 4):
  - get_current_user raises HTTP 401 if JWT is missing or invalid.
  - No groups are created when authentication fails.

Reference:
  Azure SignalR negotiate REST:
  POST /api/v1/hubs/{hub}/negotiate?negotiateVersion=1
  Returns: { url, accessToken }
"""
from __future__ import annotations

import logging
import time
from typing import Annotated

import jwt as pyjwt
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.core.auth.jwt import TokenClaims
from app.core.auth.dependencies import get_current_staff_user
from app.core.config import get_settings
from app.signalr.broadcaster import SignalRBroadcaster, _parse_connection_string
from app.signalr.group_resolver import GroupResolver, UserClaims
from app.api.v1.routers.signalr_hub import get_signalr_broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signalr", tags=["signalr"])

_resolver = GroupResolver()
_HUB_NAME = "dashboard"


class NegotiateResponse(BaseModel):
    """Response returned to Angular HubConnectionBuilder.withUrl(negotiate_url)."""

    url: str
    accessToken: str  # noqa: N815 — Angular SDK expects camelCase


@router.post(
    "/negotiate",
    response_model=NegotiateResponse,
    status_code=status.HTTP_200_OK,
    summary="Negotiate Azure SignalR client access token",
    description=(
        "Called by Angular HubConnectionBuilder before establishing WebSocket. "
        "Validates staff JWT and returns a scoped Azure SignalR client token. "
        "Returns 401 if JWT is invalid or missing."
    ),
)
async def negotiate(
    current_user: Annotated[TokenClaims, Depends(get_current_staff_user)],
    broadcaster: Annotated[SignalRBroadcaster, Depends(get_signalr_broadcaster)],
) -> NegotiateResponse:
    """Generate a client access token scoped to the user's groups.

    US-022 Scenario 4: authentication failure returns 401 before this handler runs.
    """
    settings = get_settings()

    # Map TokenClaims to UserClaims for group resolution.
    # unit_id: use first unit from units list (primary unit assignment)
    # encounter_ids: would come from custom JWT claim or DB lookup; empty for now
    user_claims = UserClaims(
        user_id=current_user.sub,
        role=current_user.role,
        unit_id=current_user.units[0] if current_user.units else None,
        encounter_ids=[],  # TODO: Populate from DB or custom JWT claim
    )
    if not current_user.units:
        logger.warning(
            "SignalR negotiate: JWT has no units claim; user will only join role group",
            extra={"user_id": current_user.sub, "role": current_user.role},
        )

    groups = _resolver.resolve(user_claims)

    endpoint, access_key = _parse_connection_string(settings.AZURE_SIGNALR_CONNECTION_STRING)
    hub_url = f"{endpoint}/client/?hub={_HUB_NAME}"

    # Generate a client-scoped token — audience is the WebSocket URL.
    # ``nameid`` is the claim Azure SignalR Service uses for user ID; keep
    # ``sub`` as well for compatibility.
    client_token = pyjwt.encode(
        {
            "aud": hub_url,
            "sub": current_user.sub,
            "nameid": current_user.sub,
            "exp": int(time.time()) + 3600,
            "groups": groups,
        },
        access_key,
        algorithm="HS256",
    )

    # Serverless mode does not honour the ``groups`` claim in the client token;
    # group membership must be managed explicitly via the REST API. Add the user
    # to their resolved groups before the client connects.
    await broadcaster.add_user_to_groups(current_user.sub, groups)

    logger.info(
        "SignalR negotiate issued",
        extra={"user_id": current_user.sub, "groups": groups},
    )

    return NegotiateResponse(url=hub_url, accessToken=client_token)
