"""Encounter realtime timeline router.

Aggregates encounter-related records into a single chronological feed:
  - ADT events (admit, transfer, discharge, cancellations)
  - Agent tasks (queued, running, completed, failed, blocked, cancelled)
  - Documents (created, approved, rejected, cancelled)
  - Pharmacist alerts (created, resolved)
  - Medication reconciliation completion
  - Audit log entries for document approvals/rejections and alert resolutions

Security: encounter:read permission. Uses read replica for query performance.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db
from app.models.adt_event import AdtEvent
from app.models.agent_task import AgentTask
from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentStatus
from app.models.encounter import Encounter
from app.models.medication import Medication
from app.models.pharmacist_alert import PharmacistAlert
from app.schemas.timeline import EncounterTimelineResponse, TimelineEvent

router = APIRouter(prefix="/encounters", tags=["encounters", "timeline"])


_EVENT_TYPE_LABELS: dict[str, str] = {
    "A01": "Admission",
    "A02": "Transfer",
    "A03": "Discharge",
    "A11": "Cancel Admission",
    "A12": "Cancel Transfer",
    "A13": "Cancel Discharge",
}


def _adt_event_type(event_type: str | None) -> str:
    if not event_type:
        return "system"
    upper = event_type.upper()
    if upper.startswith("A01"):
        return "admission"
    if upper.startswith("A02"):
        return "transfer"
    if upper.startswith("A03"):
        return "discharge"
    if upper in {"A11", "A12", "A13"}:
        return "cancellation"
    return "system"


def _agent_task_event_type(agent_type: str | None) -> str:
    return "agent_task"


def _document_event_type(doc_status: str | None) -> str:
    if not doc_status:
        return "document"
    status = doc_status.lower()
    if status == DocumentStatus.APPROVED.value:
        return "approval"
    if status == DocumentStatus.REJECTED.value:
        return "rejection"
    if status == DocumentStatus.CANCELLED.value:
        return "cancellation"
    return "document"


def _format_dt(value: datetime | None) -> datetime | None:
    """Ensure timezone-aware datetimes are returned as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _load_adt_events(
    encounter_id: uuid.UUID,
    db: AsyncSession,
) -> list[TimelineEvent]:
    stmt = (
        select(AdtEvent)
        .where(AdtEvent.encounter_id == encounter_id)
        .order_by(AdtEvent.event_timestamp.desc())
    )
    result = await db.execute(stmt)
    events: list[TimelineEvent] = []
    for row in result.scalars().all():
        event_type = (row.event_type or "").upper()
        title = _EVENT_TYPE_LABELS.get(event_type, f"ADT {event_type}")
        description = f"ADT event {event_type}"
        if row.sending_facility:
            description += f" from {row.sending_facility}"
        events.append(
            TimelineEvent(
                event_type=_adt_event_type(event_type),
                title=title,
                description=description,
                timestamp=_format_dt(row.event_timestamp),
                status=row.processing_status,
                resource_type="AdtEvent",
                resource_id=row.id,
                metadata={
                    "event_type": event_type,
                    "source_message_id": row.source_message_id,
                    "facility": row.sending_facility,
                },
            )
        )
    return events


async def _load_agent_tasks(
    encounter_id: uuid.UUID,
    db: AsyncSession,
) -> list[TimelineEvent]:
    stmt = (
        select(AgentTask)
        .where(AgentTask.encounter_id == encounter_id)
        .order_by(AgentTask.created_at.desc())
    )
    result = await db.execute(stmt)
    events: list[TimelineEvent] = []
    for task in result.scalars().all():
        agent_label = (task.agent_type or "unknown").replace("_", " ").title()
        status = task.status or "queued"
        title = f"{agent_label} Agent Task {status.replace('_', ' ').title()}"
        description_parts: list[str] = []
        if task.unit_id:
            description_parts.append(f"Unit {task.unit_id}")
        if task.target_role:
            description_parts.append(f"Target role {task.target_role}")
        if task.error_message:
            description_parts.append(f"Error: {task.error_message}")
        if task.blocked_reason:
            description_parts.append(f"Blocked: {task.blocked_reason}")
        events.append(
            TimelineEvent(
                event_type=_agent_task_event_type(task.agent_type),
                title=title,
                description=" — ".join(description_parts) if description_parts else None,
                timestamp=_format_dt(task.completed_at or task.started_at or task.created_at),
                status=status,
                resource_type="AgentTask",
                resource_id=task.id,
                metadata={
                    "agent_type": task.agent_type,
                    "unit_id": task.unit_id,
                    "target_role": task.target_role,
                    "sla_breached": task.sla_breached,
                    "retry_count": task.retry_count,
                    "error_message": task.error_message,
                    "blocked_reason": task.blocked_reason,
                },
            )
        )
    return events


async def _load_documents(
    encounter_id: uuid.UUID,
    db: AsyncSession,
) -> list[TimelineEvent]:
    stmt = (
        select(Document)
        .where(Document.encounter_id == encounter_id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    events: list[TimelineEvent] = []
    for doc in result.scalars().all():
        doc_type_label = (doc.document_type or "document").replace("_", " ").title()
        event_type = _document_event_type(doc.status)
        if event_type == "approval":
            title = f"{doc_type_label} Approved"
        elif event_type == "rejection":
            title = f"{doc_type_label} Rejected"
        elif event_type == "cancellation":
            title = f"{doc_type_label} Cancelled"
        else:
            title = f"{doc_type_label} Generated"

        metadata: dict = {
            "document_type": doc.document_type,
            "generation_type": doc.generation_type,
            "ai_assisted_label": doc.ai_assisted_label,
            "completeness_status": doc.completeness_status,
        }
        if doc.document_metadata:
            rejection_reason = doc.document_metadata.get("rejection_reason")
            if rejection_reason:
                metadata["rejection_reason"] = rejection_reason

        description = None
        if event_type == "approval":
            description = "Document approved by reviewer"
        elif event_type == "rejection":
            description = "Document rejected by reviewer"
            if metadata.get("rejection_reason"):
                description += f": {metadata['rejection_reason']}"
        elif event_type == "cancellation":
            description = "Document cancelled due to ADT cancellation event"

        events.append(
            TimelineEvent(
                event_type=event_type,
                title=title,
                description=description,
                timestamp=_format_dt(doc.approved_at or doc.updated_at or doc.created_at),
                status=doc.status,
                resource_type="Document",
                resource_id=doc.id,
                metadata=metadata,
            )
        )
    return events


async def _load_pharmacist_alerts(
    encounter_id: uuid.UUID,
    db: AsyncSession,
) -> list[TimelineEvent]:
    stmt = (
        select(PharmacistAlert)
        .where(PharmacistAlert.encounter_id == encounter_id)
        .order_by(PharmacistAlert.created_at.desc())
    )
    result = await db.execute(stmt)
    events: list[TimelineEvent] = []
    for alert in result.scalars().all():
        is_resolved = (alert.status or "").upper() == "RESOLVED"
        event_type = "resolution" if is_resolved else "alert"
        if alert.alert_type == "HIGH_RISK_DRUG_CLASS":
            title = f"High-Risk Drug Class Alert: {alert.drug_class or 'Unknown'}"
        else:
            drug_names = alert.drug_pair or []
            title = f"Drug Interaction Alert ({', '.join(drug_names)})" if drug_names else "Drug Interaction Alert"

        description = alert.interaction_description
        if is_resolved:
            resolution_label = (alert.resolution_type or "REVIEWED").replace("_", " ").title()
            title = f"{title} Resolved"
            description = f"Resolved via {resolution_label}"
            if alert.resolution_note:
                description += f" — {alert.resolution_note}"

        events.append(
            TimelineEvent(
                event_type=event_type,
                title=title,
                description=description,
                timestamp=_format_dt(alert.resolved_at or alert.created_at),
                status=alert.status,
                resource_type="PharmacistAlert",
                resource_id=alert.id,
                metadata={
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "source": alert.source,
                    "drug_pair": alert.drug_pair,
                    "drug_class": alert.drug_class,
                    "drug_name": alert.drug_name,
                    "interaction_check_status": alert.interaction_check_status,
                    "sla_breached": alert.sla_breached,
                    "resolution_type": alert.resolution_type,
                },
            )
        )
    return events


async def _load_medication_events(
    encounter_id: uuid.UUID,
    db: AsyncSession,
) -> list[TimelineEvent]:
    """Create timeline entries for medication reconciliation completion and high-severity interactions."""
    stmt = (
        select(Medication)
        .where(Medication.encounter_id == encounter_id)
        .order_by(Medication.created_at.desc())
    )
    result = await db.execute(stmt)
    medications = list(result.scalars().all())
    if not medications:
        return []

    events: list[TimelineEvent] = []
    high_severity = [m for m in medications if (m.interaction_severity or "").upper() == "HIGH"]
    if high_severity:
        drug_names = [m.drug_name for m in high_severity if m.drug_name]
        events.append(
            TimelineEvent(
                event_type="medication",
                title="High-Severity Drug Interactions Detected",
                description=f"{len(high_severity)} medication(s) flagged: {', '.join(drug_names or ['Unknown'])}",
                timestamp=_format_dt(max((m.created_at for m in high_severity if m.created_at), default=None)),
                status="ACTIVE",
                resource_type="Medication",
                resource_id=high_severity[0].id,
                metadata={
                    "count": len(high_severity),
                    "drug_names": drug_names,
                    "severity": "HIGH",
                },
            )
        )

    # Add a single reconciliation event if any medications exist
    categories = {m.reconciliation_category.value for m in medications if m.reconciliation_category}
    events.append(
        TimelineEvent(
            event_type="medication",
            title="Medication Reconciliation Available",
            description=f"{len(medications)} medication(s) reconciled" + (
                f" ({', '.join(sorted(categories))})" if categories else ""
            ),
            timestamp=_format_dt(max((m.created_at for m in medications if m.created_at), default=None)),
            status="COMPLETE",
            resource_type="Medication",
            resource_id=medications[0].id,
            metadata={
                "total_medications": len(medications),
                "categories": sorted(categories),
            },
        )
    )
    return events


async def _load_audit_events(
    encounter_id: uuid.UUID,
    db: AsyncSession,
) -> list[TimelineEvent]:
    """Surface document approvals/rejections and alert resolutions recorded in audit_log."""
    resource_id = str(encounter_id)
    stmt = (
        select(AuditLog)
        .where(
            (AuditLog.resource_type == "Document")
            | (AuditLog.resource_type == "PharmacistAlert")
            | ((AuditLog.resource_type == "Encounter") & (AuditLog.resource_id == resource_id))
        )
        .where(AuditLog.action.in_({"APPROVE", "REJECT", "RESOLVE", "CREATE", "UPDATE"}))
        .order_by(AuditLog.created_at.desc())
    )
    result = await db.execute(stmt)
    events: list[TimelineEvent] = []
    for entry in result.scalars().all():
        action = (entry.action or "").upper()
        resource_type = entry.resource_type or "Unknown"
        if action == "APPROVE":
            title = "Document Approval Logged"
            event_type = "approval"
        elif action == "REJECT":
            title = "Document Rejection Logged"
            event_type = "rejection"
        elif action == "RESOLVE":
            title = "Alert Resolution Logged"
            event_type = "resolution"
        elif action in {"CREATE", "UPDATE"}:
            title = f"{resource_type} {action.title()}d"
            event_type = "system"
        else:
            continue

        events.append(
            TimelineEvent(
                event_type=event_type,
                title=title,
                description=None,
                timestamp=_format_dt(entry.created_at),
                status=entry.outcome,
                resource_type=resource_type,
                resource_id=uuid.UUID(entry.resource_id) if _is_uuid(entry.resource_id) else None,
                metadata={
                    "action": entry.action,
                    "outcome": entry.outcome,
                    "user_id": str(entry.user_id) if entry.user_id else None,
                    "user_role": entry.user_role,
                },
            )
        )
    return events


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


@router.get(
    "/{encounter_id}/timeline",
    response_model=EncounterTimelineResponse,
    summary="Realtime encounter timeline",
    description=(
        "Returns a chronological timeline of all events for the specified encounter, "
        "including ADT events, agent tasks, documents, pharmacist alerts, medication "
        "reconciliation, and audit actions."
    ),
)
async def get_encounter_timeline(
    encounter_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "read"))],
    db: AsyncSession = Depends(get_read_db),
) -> EncounterTimelineResponse:
    """Return a realtime timeline for a specific encounter."""
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    events: list[TimelineEvent] = []
    events.extend(await _load_adt_events(encounter_id, db))
    events.extend(await _load_agent_tasks(encounter_id, db))
    events.extend(await _load_documents(encounter_id, db))
    events.extend(await _load_pharmacist_alerts(encounter_id, db))
    events.extend(await _load_medication_events(encounter_id, db))
    events.extend(await _load_audit_events(encounter_id, db))

    # Always include the encounter creation itself
    events.append(
        TimelineEvent(
            event_type="encounter_created",
            title="Encounter Created",
            description=f"Encounter status: {encounter.status}",
            timestamp=_format_dt(encounter.created_at),
            status=encounter.status,
            resource_type="Encounter",
            resource_id=encounter.id,
            metadata={
                "risk_tier": encounter.risk_tier,
                "unit": encounter.unit,
                "patient_resolution_status": encounter.patient_resolution_status,
            },
        )
    )

    # Sort descending (newest first) with None timestamps at the end
    events.sort(
        key=lambda e: (e.timestamp or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    return EncounterTimelineResponse(
        encounter_id=encounter_id,
        events=events,
        total=len(events),
    )
