"""BigQuery table schema for encounters_deidentified.

HIPAA Safe Harbor guardrail:
    This schema deliberately excludes ALL 18 PHI identifiers.
    Fields mrn, first_name, last_name, dob, phone, email are NEVER
    present in this table or in intermediate data frames.

    Only the following safe fields are included per US-062 DoD and
    HIPAA Safe Harbor method (45 CFR §164.514(b)):

Design refs:
    US-062 DoD — BigQuery schema fields
    design.md §8 — Security architecture; PHI containment
    DR-017 — De-identified analytics data requirement
"""
from google.cloud.bigquery import SchemaField, TimePartitioning, TimePartitioningType

# PHI columns that must NEVER appear in this schema
_PHI_COLUMNS_BLOCKLIST: frozenset[str] = frozenset(
    {"mrn", "first_name", "last_name", "dob", "phone", "email",
     "patient_id", "encounter_id"}
)

ENCOUNTERS_DEIDENTIFIED_SCHEMA: list[SchemaField] = [
    SchemaField("encounter_id_hash", "STRING", mode="REQUIRED",
                description="SHA-256(encounter_id + monthly_salt) — not reversible to source ID"),
    SchemaField("admit_date", "DATE", mode="REQUIRED",
                description="Admission date — partition key; day-level granularity only"),
    SchemaField("discharge_date", "DATE", mode="NULLABLE",
                description="Discharge date; NULL for encounters not yet discharged"),
    SchemaField("primary_diagnosis_code", "STRING", mode="NULLABLE",
                description="ICD-10 primary diagnosis code; not individually identifying"),
    SchemaField("risk_score", "FLOAT64", mode="NULLABLE",
                description="Readmission risk score (0.0–1.0) from ML inference service"),
    SchemaField("risk_tier", "STRING", mode="NULLABLE",
                description="Risk tier label: LOW | MEDIUM | HIGH"),
    SchemaField("unit", "STRING", mode="NULLABLE",
                description="Hospital unit code; no patient-identifying detail"),
    SchemaField("los_days", "FLOAT64", mode="NULLABLE",
                description="Length of stay in days; computed at export time"),
    SchemaField("discharge_disposition", "STRING", mode="NULLABLE",
                description="Disposition code (e.g., HOME, SNF, REHAB)"),
    SchemaField("readmitted_30d", "BOOL", mode="NULLABLE",
                description="True if patient readmitted within 30 days of discharge"),
]

ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING = TimePartitioning(
    type_=TimePartitioningType.DAY,
    field="admit_date",
)


def assert_no_phi(column_names: list[str]) -> None:
    """Raise ValueError if any PHI column name appears in the provided list.

    Called before every BigQuery write to enforce schema compliance.

    Args:
        column_names: List of column names to check.

    Raises:
        ValueError: If any PHI column is detected in the list.
    """
    violations = _PHI_COLUMNS_BLOCKLIST.intersection(set(column_names))
    if violations:
        raise ValueError(
            f"PHI columns detected in export payload — BLOCKED: {violations}"
        )
