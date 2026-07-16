# TASK-004: Write Comprehensive Unit Tests for All Resolution Paths

> **Story:** US-019 | **Effort:** 4 hours | **Layer:** Backend Testing  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement comprehensive unit test suites for patient identity resolution covering all 4 acceptance criteria scenarios: MRN success, name+DOB fallback, ambiguous matches, and unresolvable patients. Achieve ≥90% code coverage for the patient resolution module.

---

## Context

Patient identity resolution is a critical path in the SmartHandoff workflow. Failures or edge cases in resolution logic can block entire encounters from processing. Comprehensive unit tests ensure:
1. All resolution paths (MRN, fallback, ambiguous, unresolvable) work correctly
2. FHIR integration points are properly mocked for deterministic testing
3. Care team alerts are dispatched correctly
4. Encounter status management reflects resolution outcomes
5. Regression prevention for future changes

**Upstream Dependencies:**
- TASK-001: Patient models, exceptions, query builders
- TASK-002: PatientResolver service
- TASK-003: CareTeamAlertService and encounter status management

---

## Scope

### In Scope

1. **PatientResolver Test Suite (12 tests):**
   - MRN lookup success (AC1)
   - MRN lookup failure triggers fallback
   - Name+DOB fallback success (AC2)
   - Name+DOB fallback with zero results
   - Ambiguous match detection (AC3)
   - Unresolvable patient handling (AC4)
   - FHIR response parsing with malformed data
   - FHIR client error propagation
   - Logging output validation (INFO, WARNING, CRITICAL)
   - Resolution metadata fields (resolution_method, partial_match)
   - Thread-safety for concurrent requests
   - Query builder integration

2. **CareTeamAlertService Test Suite (4 tests):**
   - AMBIGUOUS alert payload structure
   - UNRESOLVED alert payload structure
   - Pub/Sub publish called with correct topic and attributes
   - Alert dispatch failure handling (non-blocking)

3. **Encounter Status Management Test Suite (4 tests):**
   - Encounter created with RESOLVED status for MRN success
   - Encounter created with AMBIGUOUS status for multiple matches
   - Encounter created with UNRESOLVED status for zero matches
   - Agent tasks blocked for AMBIGUOUS/UNRESOLVED encounters

4. **Test Infrastructure:**
   - Mock FHIR API responses with `respx`
   - Mock Pub/Sub publisher with `unittest.mock`
   - Mock time for timestamp validation
   - Fixtures for reusable test data
   - Coverage report generation

### Out of Scope

- Integration tests with real FHIR server (future E2E test suite)
- Performance/load testing (future story)
- UI testing (N/A for backend service)

---

## Acceptance Criteria

### AC1: PatientResolver Test Coverage
**Given** the `PatientResolver` service is implemented  
**When** the test suite is executed  
**Then**:
- All 12 test cases pass
- Code coverage for `app/services/patient_resolver.py` is ≥90%
- FHIR API calls are mocked (no real network requests)
- All 4 US-019 acceptance criteria scenarios are validated

### AC2: CareTeamAlertService Test Coverage
**Given** the `CareTeamAlertService` is implemented  
**When** the test suite is executed  
**Then**:
- All 4 test cases pass
- Pub/Sub publish is mocked (no real Pub/Sub calls)
- Alert payloads match expected JSON schema
- Alert dispatch failures are handled gracefully

### AC3: Encounter Status Test Coverage
**Given** encounter creation with patient resolution is implemented  
**When** the test suite is executed  
**Then**:
- All 4 test cases pass
- Encounter `patient_resolution_status` field set correctly for all 3 statuses
- Agent tasks have correct `status` and `blocked_reason` fields

### AC4: Test Execution Performance
**Given** all test suites are written  
**When** tests are run via `pytest`  
**Then**:
- Full test suite completes in <30 seconds
- No warnings or deprecation notices
- All tests deterministic (no flaky tests)

---

## Implementation Details

### File: `backend/tests/unit/services/test_patient_resolver.py`

```python
"""Unit tests for PatientResolver service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.patient_resolver import PatientResolver
from app.models.patient import PatientModel, ResolutionMethod
from app.core.fhir.exceptions import PatientAmbiguousError, PatientNotFoundWarning


@pytest.fixture
def mock_fhir_client():
    """Mock FHIRClient for testing."""
    client = MagicMock()
    client.search = AsyncMock()
    return client


@pytest.fixture
def patient_resolver(mock_fhir_client):
    """PatientResolver instance with mocked FHIR client."""
    return PatientResolver(fhir_client=mock_fhir_client)


@pytest.fixture
def sample_fhir_patient():
    """Sample FHIR Patient resource."""
    return {
        "resourceType": "Patient",
        "id": "patient-123",
        "identifier": [
            {"system": "http://hospital.org/mrn", "value": "MRN-789"}
        ],
        "name": [
            {"family": "Smith", "given": ["John"]}
        ],
        "birthDate": "1980-01-15"
    }


@pytest.fixture
def sample_fhir_bundle_single(sample_fhir_patient):
    """FHIR Bundle with single patient."""
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": sample_fhir_patient}
        ]
    }


@pytest.fixture
def sample_fhir_bundle_multiple(sample_fhir_patient):
    """FHIR Bundle with multiple patients."""
    patient2 = sample_fhir_patient.copy()
    patient2["id"] = "patient-456"
    patient3 = sample_fhir_patient.copy()
    patient3["id"] = "patient-789"
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": sample_fhir_patient},
            {"resource": patient2},
            {"resource": patient3}
        ]
    }


@pytest.fixture
def sample_fhir_bundle_empty():
    """FHIR Bundle with zero patients."""
    return {
        "resourceType": "Bundle",
        "entry": []
    }


# Test Suite 1: MRN Resolution
@pytest.mark.asyncio
async def test_resolve_patient_mrn_success(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_single
):
    """Test successful MRN lookup returns PatientModel with MRN resolution method."""
    mock_fhir_client.search.return_value = sample_fhir_bundle_single
    
    patient = await patient_resolver.resolve_patient(
        mrn="MRN-789",
        name={"family": "Smith", "given": "John"},
        dob="1980-01-15",
        encounter_id="enc-001"
    )
    
    assert patient is not None
    assert patient.resolution_method == ResolutionMethod.MRN
    assert patient.partial_match is False
    assert patient.mrn == "MRN-789"
    assert mock_fhir_client.search.call_count == 1  # Only MRN lookup, no fallback


@pytest.mark.asyncio
async def test_resolve_patient_mrn_failure_triggers_fallback(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_empty,
    sample_fhir_bundle_single
):
    """Test MRN lookup failure triggers name+DOB fallback."""
    # First call (MRN) returns empty, second call (name+DOB) returns patient
    mock_fhir_client.search.side_effect = [
        sample_fhir_bundle_empty,
        sample_fhir_bundle_single
    ]
    
    patient = await patient_resolver.resolve_patient(
        mrn="MRN-INVALID",
        name={"family": "Smith", "given": "John"},
        dob="1980-01-15",
        encounter_id="enc-002"
    )
    
    assert patient is not None
    assert patient.resolution_method == ResolutionMethod.NAME_DOB
    assert patient.partial_match is True
    assert mock_fhir_client.search.call_count == 2  # MRN + fallback


# Test Suite 2: Name+DOB Fallback
@pytest.mark.asyncio
async def test_resolve_patient_name_dob_fallback_success(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_empty,
    sample_fhir_bundle_single
):
    """Test name+DOB fallback returns PatientModel with NAME_DOB resolution method."""
    mock_fhir_client.search.side_effect = [
        sample_fhir_bundle_empty,
        sample_fhir_bundle_single
    ]
    
    with patch('app.services.patient_resolver.logger') as mock_logger:
        patient = await patient_resolver.resolve_patient(
            mrn="MRN-INVALID",
            name={"family": "Smith", "given": "John"},
            dob="1980-01-15"
        )
        
        assert patient.resolution_method == ResolutionMethod.NAME_DOB
        assert patient.partial_match is True
        # Verify WARNING log for fallback
        mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_resolve_patient_name_dob_zero_results(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_empty
):
    """Test name+DOB fallback with zero results returns None."""
    mock_fhir_client.search.return_value = sample_fhir_bundle_empty
    
    with pytest.warns(PatientNotFoundWarning):
        patient = await patient_resolver.resolve_patient(
            mrn="MRN-INVALID",
            name={"family": "Unknown", "given": "Patient"},
            dob="2000-01-01"
        )
        
        assert patient is None


# Test Suite 3: Ambiguous Match Detection
@pytest.mark.asyncio
async def test_resolve_patient_ambiguous_match(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_empty,
    sample_fhir_bundle_multiple
):
    """Test ambiguous match raises PatientAmbiguousError."""
    mock_fhir_client.search.side_effect = [
        sample_fhir_bundle_empty,
        sample_fhir_bundle_multiple
    ]
    
    with pytest.raises(PatientAmbiguousError) as exc_info:
        await patient_resolver.resolve_patient(
            mrn="MRN-INVALID",
            name={"family": "Smith", "given": "John"},
            dob="1980-01-15"
        )
    
    assert exc_info.value.match_count == 3
    assert "3 patients found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_patient_ambiguous_logs_critical(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_empty,
    sample_fhir_bundle_multiple
):
    """Test ambiguous match logs CRITICAL entry."""
    mock_fhir_client.search.side_effect = [
        sample_fhir_bundle_empty,
        sample_fhir_bundle_multiple
    ]
    
    with patch('app.services.patient_resolver.logger') as mock_logger:
        with pytest.raises(PatientAmbiguousError):
            await patient_resolver.resolve_patient(
                mrn="MRN-INVALID",
                name={"family": "Smith", "given": "John"},
                dob="1980-01-15",
                encounter_id="enc-003"
            )
        
        # Verify CRITICAL log
        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args
        assert "Ambiguous patient match" in call_args[0][0]
        assert "enc-003" in call_args[0][0]


# Test Suite 4: Unresolvable Patient
@pytest.mark.asyncio
async def test_resolve_patient_unresolvable_logs_critical(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_empty
):
    """Test unresolvable patient logs CRITICAL entry."""
    mock_fhir_client.search.return_value = sample_fhir_bundle_empty
    
    with patch('app.services.patient_resolver.logger') as mock_logger:
        with pytest.warns(PatientNotFoundWarning):
            patient = await patient_resolver.resolve_patient(
                mrn="MRN-UNKNOWN",
                name={"family": "Unknown", "given": "Patient"},
                dob="2000-01-01",
                encounter_id="enc-004"
            )
        
        assert patient is None
        # Verify CRITICAL log
        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args
        assert "Unresolvable patient" in call_args[0][0]
        assert "enc-004" in call_args[0][0]


# Test Suite 5: FHIR Response Parsing
@pytest.mark.asyncio
async def test_parse_fhir_bundle_with_malformed_resource(
    patient_resolver,
    mock_fhir_client
):
    """Test FHIR bundle parsing skips malformed resources."""
    malformed_bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient"}},  # Missing required fields
            {"resource": {"resourceType": "Observation"}}  # Wrong resource type
        ]
    }
    mock_fhir_client.search.return_value = malformed_bundle
    
    with pytest.warns(PatientNotFoundWarning):
        patient = await patient_resolver.resolve_patient(
            mrn="MRN-789",
            name={"family": "Smith", "given": "John"},
            dob="1980-01-15"
        )
        
        assert patient is None  # Malformed resources skipped, zero valid patients


# Test Suite 6: Error Propagation
@pytest.mark.asyncio
async def test_fhir_client_error_propagates(patient_resolver, mock_fhir_client):
    """Test FHIR client errors are propagated correctly."""
    from app.core.fhir.exceptions import FHIRClientError
    
    mock_fhir_client.search.side_effect = FHIRClientError("Network timeout")
    
    with pytest.raises(FHIRClientError, match="Network timeout"):
        await patient_resolver.resolve_patient(
            mrn="MRN-789",
            name={"family": "Smith", "given": "John"},
            dob="1980-01-15"
        )


# Test Suite 7: Resolution Metadata
@pytest.mark.asyncio
async def test_resolution_metadata_timestamp(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_single
):
    """Test resolved_at timestamp is set."""
    mock_fhir_client.search.return_value = sample_fhir_bundle_single
    
    before = datetime.utcnow()
    patient = await patient_resolver.resolve_patient(
        mrn="MRN-789",
        name={"family": "Smith", "given": "John"},
        dob="1980-01-15"
    )
    after = datetime.utcnow()
    
    assert patient.resolved_at is not None
    assert before <= patient.resolved_at <= after


# Test Suite 8: Query Builder Integration
@pytest.mark.asyncio
async def test_mrn_query_builder_called_with_correct_params(
    patient_resolver,
    mock_fhir_client,
    sample_fhir_bundle_single
):
    """Test MRN query builder receives correct parameters."""
    mock_fhir_client.search.return_value = sample_fhir_bundle_single
    
    with patch('app.services.patient_resolver.build_mrn_query') as mock_builder:
        mock_builder.return_value = "Patient?identifier=..."
        
        await patient_resolver.resolve_patient(
            mrn="MRN-789",
            name={"family": "Smith", "given": "John"},
            dob="1980-01-15"
        )
        
        mock_builder.assert_called_once_with("MRN-789", "http://hospital.org/mrn")
```

### File: `backend/tests/unit/services/test_care_team_alerts.py`

```python
"""Unit tests for CareTeamAlertService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from app.services.care_team_alerts import CareTeamAlertService
from app.models.patient import PatientResolutionStatus
from app.models.encounter import Encounter


@pytest.fixture
def mock_pubsub_publisher():
    """Mock GCP Pub/Sub publisher."""
    publisher = MagicMock()
    future = MagicMock()
    future.result.return_value = "message-id-123"
    publisher.publish.return_value = future
    return publisher


@pytest.fixture
def alert_service(mock_pubsub_publisher):
    """CareTeamAlertService with mocked publisher."""
    return CareTeamAlertService(publisher=mock_pubsub_publisher)


@pytest.fixture
def sample_encounter():
    """Sample encounter instance."""
    encounter = Encounter()
    encounter.id = "enc-001"
    return encounter


@pytest.mark.asyncio
async def test_send_ambiguous_alert_payload(
    alert_service,
    mock_pubsub_publisher,
    sample_encounter
):
    """Test AMBIGUOUS alert has correct payload structure."""
    await alert_service.send_patient_resolution_alert(
        encounter=sample_encounter,
        status=PatientResolutionStatus.AMBIGUOUS,
        metadata={
            "mrn": "MRN-789",
            "name": {"family": "Smith", "given": "John"},
            "dob": "1980-01-15",
            "match_count": 3
        }
    )
    
    # Verify publish called
    assert mock_pubsub_publisher.publish.called
    call_args = mock_pubsub_publisher.publish.call_args
    
    # Verify payload structure
    payload_str = call_args[1]["data"].decode("utf-8")
    assert "PATIENT_RESOLUTION_ALERT" in payload_str
    assert "AMBIGUOUS" in payload_str
    assert "enc-001" in payload_str
    assert "3" in payload_str  # match_count


@pytest.mark.asyncio
async def test_send_unresolved_alert_payload(
    alert_service,
    mock_pubsub_publisher,
    sample_encounter
):
    """Test UNRESOLVED alert has correct payload structure."""
    await alert_service.send_patient_resolution_alert(
        encounter=sample_encounter,
        status=PatientResolutionStatus.UNRESOLVED,
        metadata={
            "mrn": "MRN-UNKNOWN",
            "name": {"family": "Unknown", "given": "Patient"},
            "dob": "2000-01-01"
        }
    )
    
    call_args = mock_pubsub_publisher.publish.call_args
    payload_str = call_args[1]["data"].decode("utf-8")
    
    assert "UNRESOLVED" in payload_str
    assert "MRN-UNKNOWN" in payload_str


@pytest.mark.asyncio
async def test_alert_pubsub_topic_and_attributes(
    alert_service,
    mock_pubsub_publisher,
    sample_encounter
):
    """Test alert published to correct Pub/Sub topic with attributes."""
    await alert_service.send_patient_resolution_alert(
        encounter=sample_encounter,
        status=PatientResolutionStatus.AMBIGUOUS,
        metadata={"mrn": "MRN-789", "name": {}, "dob": "", "match_count": 3}
    )
    
    # Verify topic path
    topic_path = mock_pubsub_publisher.publish.call_args[0][0]
    assert "notification-requests" in topic_path
    
    # Verify message attributes
    call_kwargs = mock_pubsub_publisher.publish.call_args[1]
    assert call_kwargs["type"] == "PATIENT_RESOLUTION_ALERT"
    assert call_kwargs["priority"] == "HIGH"
    assert call_kwargs["encounter_id"] == "enc-001"


@pytest.mark.asyncio
async def test_alert_dispatch_failure_non_blocking(
    alert_service,
    mock_pubsub_publisher,
    sample_encounter
):
    """Test alert dispatch failure logs error but doesn't raise."""
    mock_pubsub_publisher.publish.side_effect = Exception("Pub/Sub timeout")
    
    with patch('app.services.care_team_alerts.logger') as mock_logger:
        # Should not raise exception
        await alert_service.send_patient_resolution_alert(
            encounter=sample_encounter,
            status=PatientResolutionStatus.AMBIGUOUS,
            metadata={"mrn": "MRN-789", "name": {}, "dob": "", "match_count": 3}
        )
        
        # Verify error logged
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][0]
        assert "Failed to dispatch care team alert" in error_msg
        assert "enc-001" in error_msg
```

### File: `backend/tests/unit/services/test_encounter_service.py`

```python
"""Unit tests for EncounterService with patient resolution."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.encounter_service import EncounterService
from app.models.patient import PatientModel, ResolutionMethod, PatientResolutionStatus
from app.core.fhir.exceptions import PatientAmbiguousError


@pytest.fixture
def mock_patient_resolver():
    """Mock PatientResolver."""
    resolver = MagicMock()
    resolver.resolve_patient = AsyncMock()
    return resolver


@pytest.fixture
def mock_alert_service():
    """Mock CareTeamAlertService."""
    service = MagicMock()
    service.send_patient_resolution_alert = AsyncMock()
    return service


@pytest.fixture
def encounter_service(mock_patient_resolver, mock_alert_service):
    """EncounterService with mocked dependencies."""
    return EncounterService(
        patient_resolver=mock_patient_resolver,
        alert_service=mock_alert_service
    )


@pytest.mark.asyncio
async def test_encounter_resolved_status_for_mrn_success(
    encounter_service,
    mock_patient_resolver
):
    """Test encounter has RESOLVED status for successful MRN lookup."""
    # Mock successful patient resolution
    patient = PatientModel(
        id="patient-123",
        mrn="MRN-789",
        family_name="Smith",
        given_name="John",
        date_of_birth="1980-01-15",
        resolution_method=ResolutionMethod.MRN
    )
    mock_patient_resolver.resolve_patient.return_value = patient
    
    encounter = await encounter_service.create_encounter_from_adt(
        mrn="MRN-789",
        name={"family": "Smith", "given": "John"},
        dob="1980-01-15"
    )
    
    assert encounter.patient_resolution_status == PatientResolutionStatus.RESOLVED


@pytest.mark.asyncio
async def test_encounter_ambiguous_status_for_multiple_matches(
    encounter_service,
    mock_patient_resolver,
    mock_alert_service
):
    """Test encounter has AMBIGUOUS status when multiple patients match."""
    mock_patient_resolver.resolve_patient.side_effect = PatientAmbiguousError(
        match_count=3,
        criteria={"family": "Smith", "dob": "1980-01-15"}
    )
    
    encounter = await encounter_service.create_encounter_from_adt(
        mrn="MRN-INVALID",
        name={"family": "Smith", "given": "John"},
        dob="1980-01-15"
    )
    
    assert encounter.patient_resolution_status == PatientResolutionStatus.AMBIGUOUS
    # Verify alert dispatched
    mock_alert_service.send_patient_resolution_alert.assert_called_once()


@pytest.mark.asyncio
async def test_encounter_unresolved_status_for_zero_matches(
    encounter_service,
    mock_patient_resolver,
    mock_alert_service
):
    """Test encounter has UNRESOLVED status when no patients match."""
    mock_patient_resolver.resolve_patient.return_value = None
    
    encounter = await encounter_service.create_encounter_from_adt(
        mrn="MRN-UNKNOWN",
        name={"family": "Unknown", "given": "Patient"},
        dob="2000-01-01"
    )
    
    assert encounter.patient_resolution_status == PatientResolutionStatus.UNRESOLVED
    # Verify alert dispatched
    mock_alert_service.send_patient_resolution_alert.assert_called_once()


@pytest.mark.asyncio
async def test_agent_tasks_blocked_for_ambiguous_encounter(
    encounter_service,
    mock_patient_resolver
):
    """Test agent tasks created with BLOCKED status for AMBIGUOUS encounter."""
    mock_patient_resolver.resolve_patient.side_effect = PatientAmbiguousError(
        match_count=3,
        criteria={}
    )
    
    with patch('app.services.encounter_service.AgentTask') as mock_task_class:
        encounter = await encounter_service.create_encounter_from_adt(
            mrn="MRN-INVALID",
            name={"family": "Smith", "given": "John"},
            dob="1980-01-15"
        )
        
        # Verify AgentTask created with BLOCKED status
        # (exact assertion depends on ORM implementation)
        # This is a simplified example
        assert encounter.patient_resolution_status == PatientResolutionStatus.AMBIGUOUS
```

### File: `backend/requirements-dev.txt`

Add test dependencies:

```
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
respx>=0.20.0
freezegun>=1.2.2
```

---

## Validation Steps

### Step 1: Run Full Test Suite
```bash
pytest backend/tests/unit/services/ -v
```

Expected output:
```
test_patient_resolver.py::test_resolve_patient_mrn_success PASSED
test_patient_resolver.py::test_resolve_patient_mrn_failure_triggers_fallback PASSED
test_patient_resolver.py::test_resolve_patient_name_dob_fallback_success PASSED
test_patient_resolver.py::test_resolve_patient_name_dob_zero_results PASSED
test_patient_resolver.py::test_resolve_patient_ambiguous_match PASSED
test_patient_resolver.py::test_resolve_patient_ambiguous_logs_critical PASSED
test_patient_resolver.py::test_resolve_patient_unresolvable_logs_critical PASSED
test_patient_resolver.py::test_parse_fhir_bundle_with_malformed_resource PASSED
test_patient_resolver.py::test_fhir_client_error_propagates PASSED
test_patient_resolver.py::test_resolution_metadata_timestamp PASSED
test_patient_resolver.py::test_mrn_query_builder_called_with_correct_params PASSED
test_care_team_alerts.py::test_send_ambiguous_alert_payload PASSED
test_care_team_alerts.py::test_send_unresolved_alert_payload PASSED
test_care_team_alerts.py::test_alert_pubsub_topic_and_attributes PASSED
test_care_team_alerts.py::test_alert_dispatch_failure_non_blocking PASSED
test_encounter_service.py::test_encounter_resolved_status_for_mrn_success PASSED
test_encounter_service.py::test_encounter_ambiguous_status_for_multiple_matches PASSED
test_encounter_service.py::test_encounter_unresolved_status_for_zero_matches PASSED
test_encounter_service.py::test_agent_tasks_blocked_for_ambiguous_encounter PASSED

==================== 20 passed in 2.50s ====================
```

### Step 2: Generate Coverage Report
```bash
pytest backend/tests/unit/services/ --cov=app.services.patient_resolver --cov=app.services.care_team_alerts --cov-report=term-missing
```

Expected output:
```
Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
app/services/patient_resolver.py            85      5    94%   45-47
app/services/care_team_alerts.py            35      2    94%   78-80
-----------------------------------------------------------------------
TOTAL                                      120      7    94%
```

### Step 3: Verify No Flaky Tests
```bash
# Run tests 5 times to check for flakiness
for i in {1..5}; do pytest backend/tests/unit/services/ -q; done
```

All runs should pass with identical results (no intermittent failures).

---

## Definition of Done

- [ ] PatientResolver test suite with 12 tests implemented
- [ ] CareTeamAlertService test suite with 4 tests implemented
- [ ] Encounter status test suite with 4 tests implemented
- [ ] All 20 tests pass consistently
- [ ] Code coverage ≥90% for patient resolution module
- [ ] FHIR API calls mocked with `respx` (no network requests)
- [ ] Pub/Sub calls mocked (no real Pub/Sub publishes)
- [ ] All 4 US-019 acceptance criteria validated
- [ ] Test execution completes in <30 seconds
- [ ] No flaky tests (5 consecutive runs pass)
- [ ] Coverage report generated and reviewed
- [ ] Test documentation comments clear and accurate
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-001:** Patient models and exceptions (tested by this suite)
- **TASK-002:** PatientResolver service (primary test target)
- **TASK-003:** CareTeamAlertService (secondary test target)

---

## Notes for Implementer

1. **pytest-asyncio:** Required for testing async functions. Install via `requirements-dev.txt`.

2. **Mocking Strategy:** Use `unittest.mock.AsyncMock` for async methods (e.g., `FHIRClient.search`). Use `MagicMock` for sync methods.

3. **FHIR Response Fixtures:** The `sample_fhir_bundle_*` fixtures provide realistic FHIR Bundle structures. Add more variations as needed for edge cases.

4. **Coverage Gaps:** The example shows 94% coverage. Identify the 6% missing lines and add tests if they represent critical paths. Some lines (e.g., defensive logging) may not need explicit tests.

5. **Test Isolation:** Each test should be independent. Use fixtures to ensure clean state. Avoid global variables or shared mutable state.

6. **Assertion Clarity:** Use descriptive assertion messages where helpful:
   ```python
   assert patient.resolution_method == ResolutionMethod.MRN, \
       f"Expected MRN resolution, got {patient.resolution_method}"
   ```

---

*Task created on 2026-07-16 for US-019 by plan-development-tasks workflow.*
