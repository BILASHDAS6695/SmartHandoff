"""HL7 ADT cancellation event handlers (A11, A12, A13).

Forwards ADT cancellation events to the API Gateway ``/cancel-event``
endpoint so that the encounter state machine, agent task cancellation, and
document soft-cancellation are applied atomically in the backend.

Handler contract:
  Each handler is an async callable with signature::

      async def handler(event: ADTEvent) -> None

  Registered on ``default_router`` (``app.parser.router``) at startup via
  ``register_cancellation_handlers()``.

HTTP behaviour:
  - 2xx:   success — handler returns.
  - 404:   encounter not found — logged as WARNING; handler returns (best-effort).
  - 409:   invalid state transition — re-raised as ``HL7ValidationError`` → NACK.
  - Timeout: re-raised so MLLP server sends NACK (AIR-001 SLA preserved).
  - Other errors: re-raised (triggers NACK).

Configuration (environment variables):
  API_GATEWAY_BASE_URL  — base URL of the API Gateway service.
                          Default: ``http://api-gateway:8080``
  CANCEL_TIMEOUT_S      — HTTP request timeout in seconds. Default: ``5``.

PHI safety (BR-020):
  Handlers log ``encounter_id`` (UUID) and ``event_type`` only.
  Patient MRN and other PHI fields in ``ADTEvent`` are never logged.

Design refs:
    FR-006  — A11/A12/A13 triggers must halt agent workflows
    AIR-001 — MLLP ACK within 200 ms; HTTP call is best-effort background IO
    TR-015  — 404 → best-effort; timeout → NACK
    US-015  — TASK-004
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import httpx

from app.parser.models import EventType, HL7ValidationError
from app.parser.router import default_router

if TYPE_CHECKING:
    from app.parser.models import ADTEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_BASE_URL: str = os.environ.get("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
_CANCEL_TIMEOUT_S: float = float(os.environ.get("CANCEL_TIMEOUT_S", "5"))

# ---------------------------------------------------------------------------
# Shared HTTP client (module-level singleton — reused across calls)
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the module-level shared ``httpx.AsyncClient`` instance.

    The client is created lazily on first use.  Call ``close_http_client()``
    during application shutdown (SIGTERM) to release connections.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=_API_BASE_URL,
            timeout=httpx.Timeout(_CANCEL_TIMEOUT_S),
        )
    return _http_client


async def close_http_client() -> None:
    """Gracefully close the shared HTTP client (call during SIGTERM)."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _call_cancel_api(
    encounter_id: str,
    event_type: str,
    client: httpx.AsyncClient,
) -> None:
    """POST to the API Gateway cancel-event endpoint.

    Args:
        encounter_id: UUID string of the encounter.
        event_type:   ADT cancellation code: "A11", "A12", or "A13".
        client:       ``httpx.AsyncClient`` to use for the request.

    Raises:
        httpx.TimeoutException: Request timed out — propagated so MLLP server
            can issue a NACK (AIR-001).
        HL7ValidationError:     409 state conflict — propagated as NACK.
        httpx.HTTPStatusError:  Other non-2xx / non-404 error — propagated.
    """
    url = f"/api/v1/encounters/{encounter_id}/cancel-event"
    try:
        response = await client.post(url, json={"event_type": event_type})
    except httpx.TimeoutException:
        logger.error(
            "cancellation_handler.timeout",
            extra={"encounter_id": encounter_id, "event_type": event_type},
        )
        raise  # let MLLP server issue NACK

    if response.status_code == 404:
        logger.warning(
            "cancellation_handler.unknown_encounter",
            extra={"encounter_id": encounter_id, "event_type": event_type},
        )
        return  # best-effort: unknown encounter, do not NACK

    if response.status_code == 409:
        detail = response.json().get("detail", "state conflict")
        raise HL7ValidationError(
            f"Cancel-event {event_type} rejected for encounter {encounter_id}: {detail}",
            segment="EVN",
            field="EVN-2",
        )

    response.raise_for_status()  # 5xx / unexpected → propagate

    logger.info(
        "cancellation_handler.success",
        extra={"encounter_id": encounter_id, "event_type": event_type},
    )


# ---------------------------------------------------------------------------
# Handler factory
# ---------------------------------------------------------------------------

def _make_cancellation_handler(event_type: str):
    """Return an async handler for the given ADT cancellation ``event_type``.

    Args:
        event_type: "A11", "A12", or "A13".

    Returns:
        Async callable ``async def _handler(event: ADTEvent) -> None``.
    """
    async def _handler(event: "ADTEvent") -> None:
        client = _get_http_client()
        await _call_cancel_api(
            encounter_id=str(event.encounter_id),
            event_type=event_type,
            client=client,
        )

    _handler.__name__ = f"cancel_{event_type.lower()}_handler"
    return _handler


# Module-level handler instances — importable for testing
cancel_admit_handler    = _make_cancellation_handler("A11")
cancel_transfer_handler = _make_cancellation_handler("A12")
cancel_discharge_handler = _make_cancellation_handler("A13")


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_cancellation_handlers(router=None) -> None:
    """Register A11 / A12 / A13 handlers on *router*.

    Args:
        router: ``ADTRouter`` instance.  Defaults to ``default_router`` when
                ``None`` — suitable for production startup.  Pass an isolated
                router instance in unit tests.

    Idempotent: re-registering replaces the previous handler.
    """
    if router is None:
        router = default_router

    router.register_fn(EventType.CANCEL_ADMIT,    cancel_admit_handler)
    router.register_fn(EventType.CANCEL_TRANSFER, cancel_transfer_handler)
    router.register_fn(EventType.CANCEL_DISCHARGE, cancel_discharge_handler)

    logger.info(
        "cancellation_handlers.registered",
        extra={"event_types": ["A11", "A12", "A13"]},
    )
