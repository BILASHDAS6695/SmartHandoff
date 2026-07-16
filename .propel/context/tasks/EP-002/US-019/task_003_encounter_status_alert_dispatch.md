# TASK-003: Implement Encounter Status Management and Care Team Alert Dispatch

> **Story:** US-019 | **Effort:** 6 hours | **Layer:** Backend  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement encounter status tracking for patient resolution outcomes (RESOLVED, AMBIGUOUS, UNRESOLVED) and integrate care team alerting via GCP Pub/Sub for ambiguous/unresolvable cases. Block agent tasks for encounters requiring manual patient resolution.

---

## Context

When patient identity cannot be fully resolved, the system must:
1. Record the resolution status on the encounter record for audit and reporting
2. Alert clinical staff (charge nurse, bed coordinator) for manual intervention
3. Prevent AI agents from processing encounters with unresolved patient identity

This task bridges the PatientResolver service (TASK-002) with downstream encounter workflows.

**Upstream Dependencies:**
- TASK-001: `PatientResolutionStatus` enum
- TASK-002: `PatientResolver` service
- EP-013: Pub/Sub notification infrastructure (assumed exists per design.md)

---

## Scope

### In Scope

1. **Encounter Status Field:**
   - Use `patient_resolution_status` field added in TASK-001
   - Update on encounter creation based on resolution outcome
   - Default: `RESOLVED` for successful MRN lookups
   - Set to `AMBIGUOUS` or `UNRESOLVED` based on resolution errors

2. **Care Team Alert Service:**
   - New service class: `CareTeamAlertService`
   - Method: `send_patient_resolution_alert(encounter, status, metadata)`
   - Publish alerts to GCP Pub/Sub `notification-requests` topic
   - Alert payload includes: encounter ID, MRN, patient name, DOB, resolution status, match count (for ambiguous)

3. **Alert Dispatch Integration:**
   - Call alert service from encounter creation flow when `PatientAmbiguousError` is caught
   - Call alert service when `resolve_patient()` returns `None`
   - Non-blocking async dispatch (fire-and-forget with error logging)

4. **Agent Task Blocking:**
   - Update `AgentTask` creation logic to check encounter `patient_resolution_status`
   - Set `AgentTask.status = BLOCKED` for encounters with `AMBIGUOUS` or `UNRESOLVED` status
   - Add `blocked_reason` field to `AgentTask` model (if not exists)

5. **Pub/Sub Integration:**
   - Reuse existing Pub/Sub publisher from EP-013 infrastructure
   - Topic name: `notification-requests` (per design.md Section 3.1)
   - Message attributes: `type=PATIENT_RESOLUTION_ALERT`, `priority=HIGH`

### Out of Scope

- Manual resolution UI (future story)
- Automatic patient merge detection (future enhancement)
- Email/SMS notification (handled by downstream notification service)
- Retry logic for Pub/Sub publish (handled by Pub/Sub client library)
- Unit tests (TASK-004)

---

## Acceptance Criteria

### AC1: Encounter Status Tracking
**Given** a patient is successfully resolved via MRN  
**When** an encounter is created  
**Then**:
- `encounter.patient_resolution_status` equals `RESOLVED`
- No care team alert is dispatched
- Agent tasks are created with `status=PENDING`

### AC2: Ambiguous Patient Alert
**Given** `resolve_patient()` raises `PatientAmbiguousError` with 3 matches  
**When** the encounter creation flow handles the exception  
**Then**:
- `encounter.patient_resolution_status` equals `AMBIGUOUS`
- Care team alert is published to Pub/Sub with:
  - `type: "PATIENT_RESOLUTION_ALERT"`
  - `status: "AMBIGUOUS"`
  - `match_count: 3`
  - `encounter_id`, `mrn`, `name`, `dob`
- Agent tasks are created with `status=BLOCKED, blocked_reason="Patient identity ambiguous"`
- INFO log entry: "Care team alert dispatched for encounter {id}"

### AC3: Unresolvable Patient Alert
**Given** `resolve_patient()` returns `None` (zero matches)  
**When** the encounter creation flow handles the result  
**Then**:
- `encounter.patient_resolution_status` equals `UNRESOLVED`
- Care team alert is published to Pub/Sub with:
  - `type: "PATIENT_RESOLUTION_ALERT"`
  - `status: "UNRESOLVED"`
  - `encounter_id`, `mrn`, `name`, `dob`
- Agent tasks are created with `status=BLOCKED, blocked_reason="Patient not found in EHR"`
- INFO log entry: "Care team alert dispatched for encounter {id}"

### AC4: Non-Blocking Alert Dispatch
**Given** care team alert dispatch is triggered  
**When** Pub/Sub publish fails due to network error  
**Then**:
- Encounter is still created successfully
- ERROR log entry: "Failed to dispatch care team alert: {error}"
- Alert failure does not block encounter creation

### AC5: Agent Task Blocking
**Given** an encounter has `patient_resolution_status=AMBIGUOUS`  
**When** agent tasks are created for the encounter  
**Then**:
- All agent tasks have `status=BLOCKED`
- `blocked_reason` field explains: "Patient identity ambiguous - manual resolution required"
- Tasks are visible in staff dashboard with BLOCKED status indicator

---

## Implementation Details

### File: `backend/app/services/care_team_alerts.py`

```python
"""Care team alert service for patient resolution issues."""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from google.cloud import pubsub_v1
from app.core.config import settings
from app.models.encounter import Encounter
from app.models.patient import PatientResolutionStatus

logger = logging.getLogger(__name__)

class CareTeamAlertService:
    """
    Dispatch care team alerts for patient resolution issues via GCP Pub/Sub.
    
    Alerts are sent to the 'notification-requests' topic for downstream
    processing (SMS, email, dashboard notifications).
    """
    
    def __init__(self, publisher: Optional[pubsub_v1.PublisherClient] = None):
        """
        Initialize service with Pub/Sub publisher.
        
        Args:
            publisher: GCP Pub/Sub publisher client (injected for testing)
        """
        self.publisher = publisher or pubsub_v1.PublisherClient()
        self.topic_path = f"projects/{settings.GCP_PROJECT_ID}/topics/notification-requests"
    
    async def send_patient_resolution_alert(
        self,
        encounter: Encounter,
        status: PatientResolutionStatus,
        metadata: Dict[str, Any]
    ) -> None:
        """
        Send patient resolution alert to care team via Pub/Sub.
        
        Args:
            encounter: Encounter with unresolved patient
            status: Resolution status (AMBIGUOUS or UNRESOLVED)
            metadata: Additional context (mrn, name, dob, match_count)
        
        Raises:
            Exception: Logged but not propagated (non-blocking)
        
        Example:
            >>> service = CareTeamAlertService()
            >>> await service.send_patient_resolution_alert(
            ...     encounter=encounter,
            ...     status=PatientResolutionStatus.AMBIGUOUS,
            ...     metadata={
            ...         "mrn": "MRN-789",
            ...         "name": {"family": "Smith", "given": "John"},
            ...         "dob": "1980-01-15",
            ...         "match_count": 3
            ...     }
            ... )
        """
        try:
            # Build alert payload
            payload = {
                "type": "PATIENT_RESOLUTION_ALERT",
                "priority": "HIGH",
                "status": status.value,
                "encounter_id": encounter.id,
                "mrn": metadata.get("mrn"),
                "name": metadata.get("name"),
                "dob": metadata.get("dob"),
                "match_count": metadata.get("match_count"),
                "message": self._build_alert_message(status, metadata),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Publish to Pub/Sub (fire-and-forget)
            future = self.publisher.publish(
                self.topic_path,
                data=str(payload).encode("utf-8"),
                type="PATIENT_RESOLUTION_ALERT",
                priority="HIGH",
                encounter_id=encounter.id
            )
            
            # Wait for publish to complete (async)
            message_id = future.result(timeout=5.0)
            
            logger.info(
                f"Care team alert dispatched for encounter {encounter.id}",
                extra={
                    "message_id": message_id,
                    "status": status.value,
                    "encounter_id": encounter.id
                }
            )
        
        except Exception as e:
            # Log error but don't block encounter creation
            logger.error(
                f"Failed to dispatch care team alert for encounter {encounter.id}: {e}",
                extra={"encounter_id": encounter.id, "error": str(e)},
                exc_info=True
            )
    
    def _build_alert_message(
        self,
        status: PatientResolutionStatus,
        metadata: Dict[str, Any]
    ) -> str:
        """Build human-readable alert message."""
        if status == PatientResolutionStatus.AMBIGUOUS:
            count = metadata.get("match_count", "multiple")
            return f"Manual resolution required: {count} matching patients found for MRN {metadata.get('mrn')}"
        elif status == PatientResolutionStatus.UNRESOLVED:
            return f"Patient not found in EHR for MRN {metadata.get('mrn')} - manual lookup required"
        else:
            return f"Patient resolution issue: {status.value}"
```

### File: `backend/app/services/encounter_service.py`

Update existing encounter service to integrate patient resolution:

```python
"""Encounter service with patient resolution integration."""

import logging
from typing import Optional

from app.services.patient_resolver import PatientResolver
from app.services.care_team_alerts import CareTeamAlertService
from app.models.encounter import Encounter
from app.models.patient import PatientResolutionStatus
from app.core.fhir.exceptions import PatientAmbiguousError

logger = logging.getLogger(__name__)

class EncounterService:
    """Service for encounter creation with patient resolution."""
    
    def __init__(
        self,
        patient_resolver: Optional[PatientResolver] = None,
        alert_service: Optional[CareTeamAlertService] = None
    ):
        self.patient_resolver = patient_resolver or PatientResolver()
        self.alert_service = alert_service or CareTeamAlertService()
    
    async def create_encounter_from_adt(
        self,
        mrn: str,
        name: dict,
        dob: str,
        # ... other ADT fields ...
    ) -> Encounter:
        """
        Create encounter with patient identity resolution.
        
        Args:
            mrn: Medical Record Number from ADT
            name: Patient name dict from ADT
            dob: Date of birth from ADT
        
        Returns:
            Encounter instance with patient_resolution_status set
        """
        encounter = Encounter()  # Initialize encounter record
        
        try:
            # Attempt patient resolution
            patient = await self.patient_resolver.resolve_patient(
                mrn=mrn,
                name=name,
                dob=dob,
                encounter_id=encounter.id
            )
            
            if patient:
                # Success: patient resolved
                encounter.patient_id = patient.id
                encounter.patient_resolution_status = PatientResolutionStatus.RESOLVED
                
                # Create agent tasks with PENDING status
                await self._create_agent_tasks(encounter, blocked=False)
            
            else:
                # Unresolvable: zero matches
                encounter.patient_resolution_status = PatientResolutionStatus.UNRESOLVED
                
                # Dispatch care team alert (non-blocking)
                await self.alert_service.send_patient_resolution_alert(
                    encounter=encounter,
                    status=PatientResolutionStatus.UNRESOLVED,
                    metadata={"mrn": mrn, "name": name, "dob": dob}
                )
                
                # Create blocked agent tasks
                await self._create_agent_tasks(
                    encounter,
                    blocked=True,
                    blocked_reason="Patient not found in EHR"
                )
        
        except PatientAmbiguousError as e:
            # Ambiguous: multiple matches
            encounter.patient_resolution_status = PatientResolutionStatus.AMBIGUOUS
            
            # Dispatch care team alert (non-blocking)
            await self.alert_service.send_patient_resolution_alert(
                encounter=encounter,
                status=PatientResolutionStatus.AMBIGUOUS,
                metadata={
                    "mrn": mrn,
                    "name": name,
                    "dob": dob,
                    "match_count": e.match_count
                }
            )
            
            # Create blocked agent tasks
            await self._create_agent_tasks(
                encounter,
                blocked=True,
                blocked_reason="Patient identity ambiguous - manual resolution required"
            )
        
        # Save encounter (regardless of resolution status)
        # encounter.save()  # Adjust to your ORM pattern
        
        return encounter
    
    async def _create_agent_tasks(
        self,
        encounter: Encounter,
        blocked: bool,
        blocked_reason: Optional[str] = None
    ) -> None:
        """Create agent tasks for encounter, optionally blocked."""
        from app.models.agent_task import AgentTask, TaskStatus
        
        agent_types = [
            "documentation",
            "medication_reconciliation",
            "bed_management",
            "follow_up_care",
            "patient_communication"
        ]
        
        for agent_type in agent_types:
            task = AgentTask(
                encounter_id=encounter.id,
                agent_type=agent_type,
                status=TaskStatus.BLOCKED if blocked else TaskStatus.PENDING,
                blocked_reason=blocked_reason if blocked else None
            )
            # task.save()  # Adjust to your ORM pattern
```

### File: `backend/app/models/agent_task.py`

Add `blocked_reason` field if not exists:

```python
from sqlalchemy import Column, String, Enum as SQLEnum
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

class AgentTask(Base):
    __tablename__ = "agent_tasks"
    
    # ... existing fields ...
    
    status = Column(
        SQLEnum(TaskStatus),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True
    )
    
    blocked_reason = Column(
        String,
        nullable=True,
        comment="Reason task is blocked (e.g., patient identity unresolved)"
    )
```

---

## Validation Steps

### Step 1: Resolved Patient (No Alert)
```bash
python -c "
import asyncio
from app.services.encounter_service import EncounterService

async def test():
    service = EncounterService()
    encounter = await service.create_encounter_from_adt(
        mrn='MRN-789',
        name={'family': 'Smith', 'given': 'John'},
        dob='1980-01-15'
    )
    assert encounter.patient_resolution_status == 'RESOLVED'
    print('✓ Resolved patient: no alert dispatched')

asyncio.run(test())
"
```

### Step 2: Ambiguous Patient Alert
```bash
python -c "
import asyncio
from app.services.encounter_service import EncounterService

async def test():
    service = EncounterService()
    # Assume FHIR returns 3 matching patients
    encounter = await service.create_encounter_from_adt(
        mrn='MRN-INVALID',
        name={'family': 'Smith', 'given': 'John'},
        dob='1980-01-15'
    )
    assert encounter.patient_resolution_status == 'AMBIGUOUS'
    print('✓ Ambiguous patient: alert dispatched')

asyncio.run(test())
"
```

### Step 3: Unresolvable Patient Alert
```bash
python -c "
import asyncio
from app.services.encounter_service import EncounterService

async def test():
    service = EncounterService()
    encounter = await service.create_encounter_from_adt(
        mrn='MRN-UNKNOWN',
        name={'family': 'Unknown', 'given': 'Patient'},
        dob='2000-01-01'
    )
    assert encounter.patient_resolution_status == 'UNRESOLVED'
    print('✓ Unresolvable patient: alert dispatched')

asyncio.run(test())
"
```

---

## Testing Strategy

### Unit Tests (Deferred to TASK-004)

Tests to be written in `backend/tests/unit/services/test_care_team_alerts.py`:

1. **Alert Dispatch Tests (4 tests):**
   - Test AMBIGUOUS alert payload structure
   - Test UNRESOLVED alert payload structure
   - Test Pub/Sub publish called with correct topic
   - Test alert dispatch failure logs error but doesn't raise

2. **Encounter Status Tests (3 tests):**
   - Test RESOLVED status set for successful resolution
   - Test AMBIGUOUS status set for ambiguous match
   - Test UNRESOLVED status set for zero matches

3. **Agent Task Blocking Tests (2 tests):**
   - Test agent tasks created with BLOCKED status for AMBIGUOUS encounter
   - Test agent tasks created with BLOCKED status for UNRESOLVED encounter

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Pub/Sub publish timeout blocks encounter creation | Low | Critical | Use fire-and-forget with 5s timeout; log failures |
| Alert payload exceeds Pub/Sub 10MB message limit | Low | Low | Payload is <1KB JSON; no risk |
| Care team overwhelmed by alert volume | Medium | Medium | Implement alert deduplication for same patient (future enhancement) |
| Agent tasks not visible in dashboard | Low | High | Ensure BLOCKED status included in dashboard query filters |
| Manual resolution workflow not implemented | High | Medium | Document workflow for Phase 2; staff can query DB directly in Phase 1 |

---

## Definition of Done

- [ ] `CareTeamAlertService` class implemented with `send_patient_resolution_alert()` method
- [ ] Alert payload includes all required fields (type, status, encounter_id, mrn, name, dob, match_count)
- [ ] Pub/Sub integration publishes to `notification-requests` topic
- [ ] `EncounterService.create_encounter_from_adt()` updated with resolution handling
- [ ] Encounter `patient_resolution_status` field set based on resolution outcome
- [ ] Agent tasks created with `BLOCKED` status for ambiguous/unresolved encounters
- [ ] `AgentTask.blocked_reason` field added and populated
- [ ] Alert dispatch is non-blocking (errors logged, not propagated)
- [ ] All validation steps pass locally
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-001:** PatientResolutionStatus enum (used for encounter status)
- **TASK-002:** PatientResolver service (called by encounter service)
- **TASK-004:** Unit tests (validates alert dispatch and status management)

---

## Notes for Implementer

1. **Pub/Sub Topic:** The `notification-requests` topic must exist (created in EP-013 infrastructure). Verify in GCP console before testing.

2. **Message Attributes:** Pub/Sub message attributes (`type`, `priority`) enable downstream filtering. The notification service (not in scope for this task) will route alerts based on these attributes.

3. **Fire-and-Forget:** The `future.result(timeout=5.0)` call waits for Pub/Sub acknowledgment but doesn't block indefinitely. If publish fails, the error is logged but encounter creation proceeds.

4. **ORM Patterns:** The example uses placeholder `encounter.save()` calls. Adjust to your SQLAlchemy or Django ORM patterns.

5. **Alembic Migration:** Adding `blocked_reason` to `AgentTask` requires a migration:
   ```bash
   alembic revision --autogenerate -m "Add blocked_reason to agent_tasks"
   ```

---

*Task created on 2026-07-16 for US-019 by plan-development-tasks workflow.*
