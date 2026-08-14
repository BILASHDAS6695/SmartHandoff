"""Document resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import require_role
from app.core.auth.jwt import TokenClaims, sub_to_uuid
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.document import Document, DocumentStatus
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.schemas.document_schemas import (
    DocumentRejectRequest,
    DocumentResponse,
    GenerateDocumentRequest,
)
from app.services.audit_service import write_audit_log
from app.services.document_generation_service import (
    AGENT_ROLE_DOCUMENT_MAP,
    DocumentGenerationService,
)
from app.services.patient_notification_publisher import PatientNotificationPublisher

router = APIRouter(prefix="/documents", tags=["documents"])

# US-028/US-029: Encounter-scoped document endpoints
encounters_documents_router = APIRouter(
    prefix="/encounters",
    tags=["documents"],
)


async def _notify_patient_on_document_approved(
    db: AsyncSession,
    document: Document,
) -> None:
    """Send patient-facing email/SMS when a document is approved."""
    if document.document_type.lower() != "discharge_summary":
        return

    encounter = await db.get(Encounter, document.encounter_id)
    if encounter is None or encounter.patient_id is None:
        return

    patient = await db.get(Patient, encounter.patient_id)
    if patient is None or patient.notification_opt_out:
        return

    publisher = PatientNotificationPublisher()
    await publisher.send_both(
        phone=patient.phone,
        email=patient.email,
        subject="Your discharge summary is ready",
        body=(
            f"Hi {patient.first_name or 'there'}, your discharge summary has been "
            "approved and is available in the SmartHandoff patient portal."
        ),
        patient_id=str(patient.id),
    )


@router.get("")
async def list_documents(
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "list"))],
) -> dict:
    """List documents — requires document:list permission."""
    return {"documents": [], "user": current_user.sub}


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get a single document",
    description="Returns a decrypted document including structured content and approval metadata.",
)
async def get_document(
    document_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "read"))],
    db: AsyncSession = Depends(get_read_db),
) -> DocumentResponse:
    """Get a single document — requires document:read permission."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc: Document | None = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Resolve all ORM attributes (including decrypted content) while the
    # read session is still open.
    if doc.reviewed_by_user:
        _ = doc.reviewed_by_user.full_name

    response = DocumentResponse.model_validate(doc)
    if doc.reviewed_by_user:
        response.reviewed_by_display_name = doc.reviewed_by_user.full_name
    return response


@encounters_documents_router.get(
    "/{encounter_id}/documents",
    response_model=list[DocumentResponse],
    summary="List documents for an encounter",
    description="Returns decrypted documents scoped to the encounter, ordered by creation time descending.",
)
async def list_encounter_documents(
    encounter_id: uuid.UUID,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("document", "list"))
    ],
    db: AsyncSession = Depends(get_read_db),
) -> list[DocumentResponse]:
    """List all documents for a specific encounter."""
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    result = await db.execute(
        select(Document)
        .where(Document.encounter_id == encounter_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()

    # Eagerly touch relationships so decryption/loading happens inside the
    # open read session before the objects are serialized.
    for doc in docs:
        if doc.reviewed_by_user:
            _ = doc.reviewed_by_user.full_name

    responses: list[DocumentResponse] = []
    for doc in docs:
        response = DocumentResponse.model_validate(doc)
        if doc.reviewed_by_user:
            response.reviewed_by_display_name = doc.reviewed_by_user.full_name
        responses.append(response)

    return responses


@encounters_documents_router.post(
    "/{encounter_id}/documents/generate",
    response_model=DocumentResponse,
    summary="Generate a role-based clinical document",
    description=(
        "Generates a Document record for the encounter based on the requested agent role. "
        "Content is built from patient demographics, encounter details, medications, and "
        "pharmacist alerts. The generated document is returned with status PENDING_APPROVAL."
    ),
    responses={
        200: {"description": "Document generated successfully"},
        400: {"description": "Unsupported agent role"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Encounter not found"},
    },
)
async def generate_encounter_document(
    encounter_id: uuid.UUID,
    request: GenerateDocumentRequest,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("document", "write"))
    ],
    db: AsyncSession = Depends(get_write_db),
) -> DocumentResponse:
    """Generate a clinical document for an encounter from the selected agent role.

    Args:
        encounter_id: UUID of the encounter.
        request: Contains the agent_role that determines document type and content.
        current_user: JWT claims from authenticated user.
        db: Database session.

    Returns:
        DocumentResponse for the newly generated document.

    Raises:
        400: Unsupported agent role.
        404: Encounter not found.
        403: User lacks document:write permission.
    """
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    agent_role = request.agent_role.lower()
    if agent_role not in AGENT_ROLE_DOCUMENT_MAP:
        supported = ", ".join(AGENT_ROLE_DOCUMENT_MAP)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported agent role '{request.agent_role}'. Use: {supported}",
        )

    target_document_type = AGENT_ROLE_DOCUMENT_MAP[agent_role]["document_type"]

    # Guard against duplicate / unauthorized generation workflows:
    #   - A plain generate cannot create another copy if any document of this type
    #     already exists (draft/pending/rejected). The user must Regenerate.
    #   - Regenerate is not allowed once a document of this type is approved.
    existing_result = await db.execute(
        select(Document)
        .where(Document.encounter_id == encounter_id)
        .where(Document.document_type == target_document_type)
        .order_by(Document.created_at.desc())
    )
    existing_docs = list(existing_result.scalars().all())

    if request.regenerate:
        if any(d.status == DocumentStatus.APPROVED.value for d in existing_docs):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An approved document of this type already exists. Approved documents cannot be regenerated.",
            )
    else:
        if existing_docs:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A document of this type already exists. Use Regenerate to create a new version with latest data.",
            )

    service = DocumentGenerationService(db)
    document = await service.generate(
        encounter_id, agent_role, regenerate=request.regenerate
    )

    await write_audit_log(
        db=db,
        action="DOCUMENT_GENERATED",
        resource_type="Document",
        resource_id=document.id,
        performed_by=sub_to_uuid(current_user.sub),
        metadata={
            "document_type": document.document_type,
            "encounter_id": str(encounter_id),
            "agent_role": agent_role,
            "generation_type": document.generation_type,
        },
    )

    return DocumentResponse.model_validate(document)


@router.post("")
async def create_document(
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "write"))],
) -> dict:
    """Create a document — requires document:write permission."""
    return {"created": True, "user": current_user.sub}


@router.patch("/{document_id}/approve")
async def approve_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_role(["PHYSICIAN", "ADVANCED_PRACTICE"]))],
) -> DocumentResponse:
    """
    Approve a document — physician or advanced_practice role only (US-029 Scenario 4).

    Transition document status PENDING_REVIEW → APPROVED and record approval metadata.

    Sets:
      - Document.status           = APPROVED
      - Document.approved_at      = UTC now
      - Document.reviewed_by_user_id = sub_to_uuid(current_user.sub)
      - Document.ai_assisted_label remains True (permanent provenance — must NOT be reset)

    RBAC: restricted to `PHYSICIAN` and `ADVANCED_PRACTICE` JWT roles (US-029 DoD).
    Returns 403 for all other roles.
    Returns 404 if document not found.
    Returns 409 if document is already APPROVED or REJECTED.

    A HIPAA audit log entry is written unconditionally on success.
    """
    # Fetch document with eager-loaded reviewed_by_user relationship
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
    )
    doc: Document | None = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if doc.status == DocumentStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already approved.",
        )
    if doc.status == DocumentStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected documents cannot be approved directly. Regenerate the document.",
        )

    # ── Apply approval fields (US-029 Scenario 4) ─────────────────────────────
    doc.status = DocumentStatus.APPROVED.value
    doc.approved_at = datetime.now(tz=timezone.utc)
    doc.reviewed_by_user_id = sub_to_uuid(current_user.sub)
    # NOTE: doc.ai_assisted_label is deliberately NOT modified here.
    #       The permanent provenance flag must remain True after approval (BR-011).

    # ── HIPAA audit log (US-029 DoD) ──────────────────────────────────────────
    await write_audit_log(
        db=db,
        action="DOCUMENT_APPROVED",
        resource_type="Document",
        resource_id=document_id,
        performed_by=sub_to_uuid(current_user.sub),
        metadata={
            "document_type": doc.document_type,
            "encounter_id": str(doc.encounter_id),
            "ai_assisted_label": doc.ai_assisted_label,
            "approved_at": doc.approved_at.isoformat(),
        },
    )

    await db.commit()
    await db.refresh(doc)

    # Notify patient after successful commit (US-064)
    await _notify_patient_on_document_approved(db, doc)

    # Build response with resolved display name
    response = DocumentResponse.model_validate(doc)
    if doc.reviewed_by_user:
        response.reviewed_by_display_name = doc.reviewed_by_user.full_name

    return response


@router.patch("/{document_id}/reject")
async def reject_document(
    document_id: uuid.UUID,
    request: DocumentRejectRequest,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_role(["PHYSICIAN", "ADVANCED_PRACTICE"]))],
) -> DocumentResponse:
    """
    Reject a document — physician or advanced_practice role only.

    Transition document status to REJECTED and record reviewer metadata.
    The rejection reason is stored in the document metadata for audit.

    Sets:
      - Document.status           = REJECTED
      - Document.reviewed_by_user_id = sub_to_uuid(current_user.sub)
      - Document.metadata['rejection_reason'] = request.rejection_reason

    RBAC: restricted to `PHYSICIAN` and `ADVANCED_PRACTICE` JWT roles.
    Returns 403 for all other roles.
    Returns 404 if document not found.
    Returns 409 if document is already APPROVED or REJECTED.

    A HIPAA audit log entry is written unconditionally on success.
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc: Document | None = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if doc.status == DocumentStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approved documents cannot be rejected.",
        )
    if doc.status == DocumentStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already rejected.",
        )

    doc.status = DocumentStatus.REJECTED.value
    doc.reviewed_by_user_id = sub_to_uuid(current_user.sub)

    meta = doc.document_metadata or {}
    meta["rejection_reason"] = request.rejection_reason
    meta["rejected_at"] = datetime.now(tz=timezone.utc).isoformat()
    doc.document_metadata = meta

    await write_audit_log(
        db=db,
        action="DOCUMENT_REJECTED",
        resource_type="Document",
        resource_id=document_id,
        performed_by=sub_to_uuid(current_user.sub),
        metadata={
            "document_type": doc.document_type,
            "encounter_id": str(doc.encounter_id),
            "ai_assisted_label": doc.ai_assisted_label,
            "rejection_reason": request.rejection_reason,
        },
    )

    await db.commit()
    await db.refresh(doc)

    response = DocumentResponse.model_validate(doc)
    if doc.reviewed_by_user:
        response.reviewed_by_display_name = doc.reviewed_by_user.full_name

    return response
