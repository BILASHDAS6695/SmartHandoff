---
id: TASK-002
title: "CSV Exporter — Streaming Response, Column Definitions & PHI De-identification Guard"
user_story: US-063
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-063/TASK-001, US-061/TASK-001]
---

# TASK-002: CSV Exporter — Streaming Response, Column Definitions & PHI De-identification Guard

> **Story:** US-063 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-063 requires a CSV export that streams aggregated KPI data with correct column headers and zero PHI fields. This task implements `api-gateway/app/export/csv_exporter.py`, which:

- Accepts a `list[KpiDataPoint]` returned by `KpiQueryService` (from US-061/TASK-001)
- Converts the list to a `pandas.DataFrame`
- Enforces a PHI column blocklist to prevent accidental leakage from future schema changes
- Streams the result as a `text/csv` `StreamingResponse` with a `Content-Disposition: attachment` header
- Generates a filename of the form `kpi_report_{from_date}_{to_date}.csv`

**Design references:**
- design.md ADR-007 — PHI never in plaintext; PHI containment enforced at every layer
- design.md §5.1 TR-001 — API p95 <500 ms; `StreamingResponse` avoids buffering full CSV in memory
- US-063 AC Scenario 1 — file downloads within 5 seconds for a 1-year date range
- US-063 AC Scenario 3 — CSV contains only aggregated metrics (averages, counts, rates) and dates/unit names
- US-063 Technical Notes — `StreamingResponse` with `text/csv` media type

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | CSV file streams within 5 s for 365-day range; column headers present on first row |
| Scenario 3 | `_PHI_BLOCKED_COLUMNS` enforcement raises `ValueError` if any PHI field reaches the exporter |

---

## Implementation Steps

### 1. Implement `api-gateway/app/export/csv_exporter.py`

```python
"""CSV streaming exporter for KPI analytics reports.

Converts a list of KpiDataPoint records to a streaming CSV response with
correct headers and PHI de-identification guard.

Output contract:
    - Media type: text/csv
    - Content-Disposition: attachment; filename=kpi_report_{from}_{to}.csv
    - Columns: date, unit_name, avg_los_hours, discharge_count,
               readmission_rate, medication_reconciliation_rate,
               handoff_completion_rate, agent_success_rate
    - No PHI columns: patient names, MRNs, DOBs, encounter IDs, phone,
                      email, or any individually identifiable field are
                      blocked by _PHI_BLOCKED_COLUMNS.

Design refs:
    design.md ADR-007 — PHI containment at every layer
    US-063 AC Scenario 3 — zero PHI in CSV output
    US-063 Technical Notes — StreamingResponse with text/csv media type
"""
from __future__ import annotations

import datetime
import io
from typing import Generator

import pandas as pd
from fastapi.responses import StreamingResponse

from app.analytics.schemas import KpiDataPoint

# Explicit allowlist of columns that are safe to include in export.
# Any column NOT in this set is silently dropped before the DataFrame is built.
_SAFE_COLUMNS: list[str] = [
    "date",
    "unit_name",
    "avg_los_hours",
    "discharge_count",
    "readmission_rate",
    "medication_reconciliation_rate",
    "handoff_completion_rate",
    "agent_success_rate",
]

# PHI field names that must never appear in the CSV output.
# Guard raises ValueError if any of these are detected in the data rows.
_PHI_BLOCKED_COLUMNS: frozenset[str] = frozenset(
    {
        "patient_name",
        "first_name",
        "last_name",
        "mrn",
        "dob",
        "date_of_birth",
        "phone",
        "email",
        "encounter_id",
        "ssn",
        "address",
    }
)


def build_csv_streaming_response(
    kpi_data: list[KpiDataPoint],
    from_date: datetime.date,
    to_date: datetime.date,
) -> StreamingResponse:
    """Build a streaming CSV response from KPI data points.

    Args:
        kpi_data:   List of de-identified KPI data points from KpiQueryService.
        from_date:  Report start date (used for filename).
        to_date:    Report end date (used for filename).

    Returns:
        StreamingResponse with text/csv media type and attachment header.

    Raises:
        ValueError: If any PHI column names are detected in the input data.
    """
    _assert_no_phi(kpi_data)
    filename = f"kpi_report_{from_date.isoformat()}_{to_date.isoformat()}.csv"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}

    return StreamingResponse(
        _csv_generator(kpi_data),
        media_type="text/csv",
        headers=headers,
    )


def _csv_generator(kpi_data: list[KpiDataPoint]) -> Generator[str, None, None]:
    """Yield CSV rows as string chunks for StreamingResponse.

    Builds a DataFrame from the safe column allowlist, then yields the CSV
    content line by line to avoid buffering the full file in memory.

    Args:
        kpi_data: De-identified KPI data points.

    Yields:
        CSV row strings (header row + one row per KpiDataPoint).
    """
    if not kpi_data:
        # Yield header-only CSV for empty date ranges
        yield ",".join(_SAFE_COLUMNS) + "\n"
        return

    rows = [
        {col: getattr(point, col, None) for col in _SAFE_COLUMNS}
        for point in kpi_data
    ]
    df = pd.DataFrame(rows, columns=_SAFE_COLUMNS)

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)

    for line in buffer:
        yield line


def _assert_no_phi(kpi_data: list[KpiDataPoint]) -> None:
    """Raise ValueError if any PHI field names are present in the data.

    Inspects the attribute names of the first KpiDataPoint (if present)
    against the _PHI_BLOCKED_COLUMNS blocklist.

    Args:
        kpi_data: List of KPI data points to inspect.

    Raises:
        ValueError: Listing any blocked field names found on the schema.
    """
    if not kpi_data:
        return

    data_fields = set(kpi_data[0].__dict__.keys()) | set(
        kpi_data[0].__class__.__fields__.keys()
        if hasattr(kpi_data[0].__class__, "__fields__")
        else []
    )
    violations = data_fields & _PHI_BLOCKED_COLUMNS
    if violations:
        raise ValueError(
            f"PHI column(s) detected in KPI export data — blocked fields: {sorted(violations)}. "
            "Review KpiDataPoint schema and KpiQueryService to remove PHI before export."
        )
```

### 2. Verify `KpiDataPoint` schema in `api-gateway/app/analytics/schemas.py`

Confirm (from US-061/TASK-001) that `KpiDataPoint` contains only the safe fields listed in `_SAFE_COLUMNS`. If the schema has been extended with any PHI field since US-061, remove it or move it to a separate patient-level schema.

Expected safe fields:

```python
class KpiDataPoint(BaseModel):
    date: datetime.date
    unit_name: str
    avg_los_hours: float
    discharge_count: int
    readmission_rate: float
    medication_reconciliation_rate: float
    handoff_completion_rate: float
    agent_success_rate: float
```

### 3. Add `pandas` to backend dependencies

```bash
# api-gateway/requirements.txt — add if not already present
echo "pandas>=2.2.0" >> api-gateway/requirements.txt
```

---

## Validation Checklist

- [ ] `GET /api/v1/analytics/export?format=csv&from=2025-01-01&to=2025-12-31` with `MANAGER` JWT → 200 with `text/csv` content type
- [ ] `Content-Disposition` header contains `filename=kpi_report_2025-01-01_2025-12-31.csv`
- [ ] First row of CSV contains all 8 column headers from `_SAFE_COLUMNS`
- [ ] No column names from `_PHI_BLOCKED_COLUMNS` appear in the response
- [ ] Empty date range (no KPI rows) → CSV with header row only, no error
- [ ] Response for 365-day range begins streaming within 5 seconds (local dev benchmark)
- [ ] `_assert_no_phi` raises `ValueError` when a PHI-named attribute is injected into the data fixture (manual test)
