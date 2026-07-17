---
id: TASK-002
title: "GET /api/v1/beds/recommend — Bed Recommendation Endpoint and No-Beds Advisory"
user_story: US-037
epic: EP-006
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-037/TASK-001, US-035/TASK-005, US-012]
---

# TASK-002: GET /api/v1/beds/recommend — Bed Recommendation Endpoint and No-Beds Advisory

> **Story:** US-037 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-037 requires a `GET /api/v1/beds/recommend?encounter_id={id}` endpoint in the `api-gateway` service. The endpoint:

1. Fetches the encounter record and its `ADTEvent` to build a `PatientAdmissionProfile`
2. Queries `mv_bed_board` (read replica) for all VACANT beds in the patient's target unit
3. Passes the profile and bed list to `BedScoringAlgorithm.score_and_rank()` (TASK-001)
4. Returns the top 5 ranked beds with `score_breakdown` for transparency (AC Scenario 1)
5. If no VACANT beds exist in the target unit, returns an advisory response with the nearest available unit and estimated wait minutes (AC Scenario 4)

All access is JWT-authenticated; `BedManager` and `Admin` roles only. Audit log event emitted per request. Response time must be <500ms p95 — reads go to the read replica via `mv_bed_board` (TR-001, ADR-006).

**Design references:**
- US-037 AC Scenario 1 — `GET /api/v1/beds/recommend?encounter_id={id}`; ≥3 beds; `score_breakdown`
- US-037 AC Scenario 4 — empty `recommendations=[]`; `advisory` object with nearest unit + wait
- US-037 Technical Notes — query `mv_bed_board` (replica); encounter features from `ADTEvent`; return top 5
- design.md §3.3 — FastAPI API structure; `/api/v1/beds` router
- design.md §5.1 TR-001 — GET endpoints via read replica; p95 <500ms
- design.md §8.3 — RBAC: BedManager and Admin only
- ADR-006 — CQRS: GET queries to read replica

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `GET /api/v1/beds/recommend?encounter_id={id}` returns ≥3 beds ranked by score with `score_breakdown` |
| Scenario 4 | Empty unit → `recommendations=[]`; `advisory.message`, `advisory.available_unit`, `advisory.estimated_wait_minutes` |

---

## Implementation Steps

### 1. Create Pydantic response schemas

Add to `api-gateway/app/routers/beds.py` (extend existing file from US-035/TASK-005):

```python
# ---------------------------------------------------------------------------
# US-037 — Bed Recommendation schemas
# ---------------------------------------------------------------------------

class ScoreBreakdownResponse(BaseModel):
    """Per-factor score transparency for a recommended bed (AC Scenario 1)."""

    acuity_match: float = Field(..., ge=0.0, le=1.0)
    care_type_match: float = Field(..., ge=0.0, le=1.0)
    isolation_match: float = Field(..., ge=0.0, le=1.0)
    gender_match: float = Field(..., ge=0.0, le=1.0)


class BedRecommendationItem(BaseModel):
    """A single ranked bed in the recommendation list (AC Scenario 1)."""

    bed_id: str
    unit: str
    room: str
    bed_number: str
    score: float = Field(..., ge=0.0, le=1.0, description="Weighted composite score 0–1")
    score_breakdown: ScoreBreakdownResponse


class NoBedsAdvisory(BaseModel):
    """Advisory payload returned when no beds are available (AC Scenario 4)."""

    message: str
    available_unit: str | None = None
    estimated_wait_minutes: int | None = None


class BedRecommendationResponse(BaseModel):
    """Response body for GET /api/v1/beds/recommend."""

    encounter_id: str
    recommendations: list[BedRecommendationItem]
    advisory: NoBedsAdvisory | None = None
```

### 2. Add `GET /api/v1/beds/recommend` endpoint to `api-gateway/app/routers/beds.py`

```python
@router.get(
    "/recommend",
    response_model=BedRecommendationResponse,
    summary="Recommend optimal bed assignments for an incoming patient",
    description=(
        "Scores all VACANT beds against the patient's admission profile "
        "(acuity, care type, isolation, gender) and returns the top 5 ranked "
        "recommendations. Restricted to BedManager and Admin roles."
    ),
)
async def recommend_beds(
    encounter_id: Annotated[
        uuid.UUID,
        Query(description="UUID of the active encounter (A01 pending admit)")
    ],
    read_db: AsyncSession = Depends(get_read_db),
    write_db: AsyncSession = Depends(get_write_db),
    current_user=Depends(require_role(["BedManager", "Admin"])),
) -> BedRecommendationResponse:
    """Score VACANT beds for an incoming patient encounter.

    Steps:
        1. Load encounter + ADTEvent from read replica.
        2. Build PatientAdmissionProfile from encounter features.
        3. Query mv_bed_board for VACANT beds in the target unit.
        4. Run BedScoringAlgorithm.score_and_rank().
        5. Emit HIPAA audit log entry.
        6. Return ranked recommendations or no-beds advisory.

    Design refs:
        US-037 AC Scenario 1  — ≥3 results with score_breakdown
        US-037 AC Scenario 4  — empty results → advisory with nearest unit
        design.md §8.3        — BedManager and Admin RBAC
        ADR-006               — read replica for GET queries
    """
    encounter_uuid = str(encounter_id)

    # ------------------------------------------------------------------
    # 1. Load encounter + ADT event
    # ------------------------------------------------------------------
    from app.models.encounter import Encounter
    from app.models.adt_event import ADTEvent

    encounter_row = await read_db.execute(
        select(Encounter).where(
            Encounter.id == encounter_uuid,
            Encounter.status == "REGISTERED",
        )
    )
    encounter = encounter_row.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active encounter {encounter_uuid} not found.",
        )

    adt_row = await read_db.execute(
        select(ADTEvent)
        .where(ADTEvent.encounter_id == encounter_uuid)
        .order_by(ADTEvent.created_at.desc())
        .limit(1)
    )
    adt_event = adt_row.scalar_one_or_none()
    if adt_event is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No ADT event found for encounter {encounter_uuid}.",
        )

    # ------------------------------------------------------------------
    # 2. Build admission profile (no PHI — coded fields only)
    # ------------------------------------------------------------------
    profile = PatientAdmissionProfile(
        acuity_level=adt_event.acuity_level or "MED-SURG",
        admit_type=adt_event.admit_type or "GENERAL",
        isolation_required=bool(adt_event.isolation_required),
        gender=adt_event.patient_gender or "other",
    )

    # ------------------------------------------------------------------
    # 3. Query VACANT beds from mv_bed_board (read replica)
    # ------------------------------------------------------------------
    target_unit: str = adt_event.target_unit or ""
    vacant_beds_result = await read_db.execute(
        text(
            """
            SELECT bed_id, unit, room, bed_number, bed_type, care_type,
                   isolation_capable, gender_designation
            FROM   mv_bed_board
            WHERE  status = 'VACANT'
              AND  unit   = :unit
            ORDER BY bed_id
            """
        ),
        {"unit": target_unit},
    )
    vacant_beds = [dict(row._mapping) for row in vacant_beds_result]

    # ------------------------------------------------------------------
    # 4. Score and rank
    # ------------------------------------------------------------------
    from app.agents.bed_management.scoring import BedScoringAlgorithm, PatientAdmissionProfile

    algo = BedScoringAlgorithm()
    ranked = algo.score_and_rank(profile, vacant_beds)

    # ------------------------------------------------------------------
    # 5. Audit log
    # ------------------------------------------------------------------
    await emit_audit_event(
        db=write_db,
        user_id=current_user.sub,
        action="BED_RECOMMENDATION_REQUESTED",
        resource_type="encounter",
        resource_id=encounter_uuid,
        metadata={
            "candidate_bed_count": len(vacant_beds),
            "recommendation_count": len(ranked),
            "target_unit": target_unit,
        },
    )

    # ------------------------------------------------------------------
    # 6. Build response
    # ------------------------------------------------------------------
    if ranked:
        items = [
            BedRecommendationItem(
                bed_id=r.bed_id,
                unit=r.unit,
                room=r.room,
                bed_number=r.bed_number,
                score=r.score,
                score_breakdown=ScoreBreakdownResponse(
                    acuity_match=r.score_breakdown.acuity_match,
                    care_type_match=r.score_breakdown.care_type_match,
                    isolation_match=r.score_breakdown.isolation_match,
                    gender_match=r.score_breakdown.gender_match,
                ),
            )
            for r in ranked
        ]
        return BedRecommendationResponse(
            encounter_id=encounter_uuid,
            recommendations=items,
        )

    # No beds available — build advisory (AC Scenario 4)
    advisory = await _build_no_beds_advisory(read_db, target_unit)
    return BedRecommendationResponse(
        encounter_id=encounter_uuid,
        recommendations=[],
        advisory=advisory,
    )
```

### 3. Implement `_build_no_beds_advisory()` helper

```python
async def _build_no_beds_advisory(
    read_db: AsyncSession,
    exhausted_unit: str,
) -> NoBedsAdvisory:
    """Find the nearest unit with VACANT beds and estimate wait time.

    Nearest unit is defined as the unit with the highest VACANT bed count
    that is not the exhausted unit. Wait estimate uses a static lookup table
    (average historical turnover per unit) — a Scikit-learn model is out of
    scope for US-037 (US-036 covers discharge time prediction for known patients,
    not queue estimation).

    Design ref:
        US-037 AC Scenario 4 — advisory with nearest available unit + wait_minutes
    """
    # Unit-level VACANT count from mv_bed_board
    result = await read_db.execute(
        text(
            """
            SELECT   unit,
                     COUNT(*) AS vacant_count
            FROM     mv_bed_board
            WHERE    status = 'VACANT'
              AND    unit  != :exhausted_unit
            GROUP BY unit
            ORDER BY vacant_count DESC
            LIMIT    1
            """
        ),
        {"exhausted_unit": exhausted_unit},
    )
    row = result.mappings().first()

    if row is None:
        return NoBedsAdvisory(
            message=(
                f"No beds available in {exhausted_unit}. "
                "No other units currently have available beds."
            ),
        )

    nearest_unit: str = row["unit"]
    # Estimated wait: 30 min baseline + 15 min per occupied bed over capacity (simplified)
    estimated_wait: int = 30  # minutes — static baseline; refined in Phase 2

    return NoBedsAdvisory(
        message=(
            f"No beds available in requested unit {exhausted_unit}. "
            f"Nearest available unit: {nearest_unit}"
        ),
        available_unit=nearest_unit,
        estimated_wait_minutes=estimated_wait,
    )
```

### 4. Register the `beds` router (confirm already registered from US-035)

Verify `api-gateway/app/main.py` includes:

```python
from app.routers.beds import router as beds_router
app.include_router(beds_router, prefix="/api/v1")
```

No change required if US-035/TASK-005 already added the router.

---

## Validation Checklist

- [ ] `GET /api/v1/beds/recommend?encounter_id={valid-uuid}` returns HTTP 200 with `recommendations` array
- [ ] Response includes `bed_id`, `unit`, `room`, `score`, `score_breakdown` for each item
- [ ] Encounter not found → HTTP 404
- [ ] No ADT event → HTTP 422
- [ ] No VACANT beds in unit → `recommendations=[]`, `advisory` object populated
- [ ] Advisory includes `available_unit` and `estimated_wait_minutes` when alternate unit exists
- [ ] Unauthenticated request → HTTP 401
- [ ] Nurse role request → HTTP 403
- [ ] Audit event `BED_RECOMMENDATION_REQUESTED` written for every successful call
- [ ] No PHI in logs or audit metadata (encounter_id, counts, unit only)
- [ ] Response time p95 < 500 ms (read replica + mv_bed_board indexed query)

---

## Files Modified / Created

| File | Change |
|------|--------|
| `api-gateway/app/routers/beds.py` | Add recommendation schemas + endpoint + advisory helper |
