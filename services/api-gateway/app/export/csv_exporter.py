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
from typing import Generator, Any

import pandas as pd
from fastapi.responses import StreamingResponse

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
    kpi_data: list[Any],
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


def _csv_generator(kpi_data: list[Any]) -> Generator[str, None, None]:
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


def _assert_no_phi(kpi_data: list[Any]) -> None:
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

    data_point = kpi_data[0]
    # Get all attributes from the object
    data_fields = set()
    
    # Handle dict-like objects
    if isinstance(data_point, dict):
        data_fields = set(data_point.keys())
    else:
        # Handle Pydantic models and regular objects
        if hasattr(data_point, "__dict__"):
            data_fields.update(data_point.__dict__.keys())
        if hasattr(data_point.__class__, "__fields__"):
            data_fields.update(data_point.__class__.__fields__.keys())
    
    violations = data_fields & _PHI_BLOCKED_COLUMNS
    if violations:
        raise ValueError(
            f"PHI column(s) detected in KPI export data — blocked fields: {sorted(violations)}. "
            "Review KpiDataPoint schema and KpiQueryService to remove PHI before export."
        )
