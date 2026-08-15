"""Query service for KPI analytics — reads exclusively from the read replica.

All methods in this service use the read-replica AsyncSession.
No write operations are permitted here.

Metrics are computed on-demand from base tables so the dashboard is resilient
to the mv_kpi_daily materialised view schema drift.

Design refs:
    design.md ADR-006 — CQRS read/write session routing
    design.md TR-010 — 100% of dashboard GET requests routed to read replica
    US-061 Technical Notes — mv_kpi_daily columns
"""
from __future__ import annotations

import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import (
    HighRiskEncounter,
    HighRiskEncounterResponse,
    KpiDataPoint,
    KpiResponse,
)


class KpiQueryService:
    """Encapsulates all read-replica queries for the KPI analytics endpoint.

    Inject the read-replica AsyncSession — never the write session.
    """

    def __init__(self, read_session: AsyncSession) -> None:
        self._session = read_session

    async def get_kpis(
        self,
        from_date: datetime.date,
        to_date: datetime.date,
        unit: str | None,
        accessible_units: list[str],
    ) -> KpiResponse:
        """Return aggregated KPI data points filtered by date range and unit.

        Args:
            from_date: Inclusive start date for the query window.
            to_date: Inclusive end date for the query window.
            unit: Optional unit filter. If None, returns all accessible_units.
            accessible_units: Units the requesting manager is permitted to view
                              (derived from app_user.units — enforced upstream in RBAC).

        Returns:
            KpiResponse with de-identified aggregated data points.
        """
        if not accessible_units:
            return KpiResponse(
                from_date=from_date,
                to_date=to_date,
                unit=unit,
                data=[],
                total_rows=0,
            )

        # Build a date series so missing days still appear with zero/NULL metrics.
        sql = text(
            """
            WITH date_series AS (
                SELECT generate_series(
                    :from_date,
                    :to_date,
                    '1 day'::interval
                )::date AS ds_date
            ),
            units AS (
                SELECT DISTINCT UPPER(unit) AS unit_name
                FROM encounter
                WHERE deleted_at IS NULL
                  AND unit IS NOT NULL
                  AND UPPER(unit) = ANY(:accessible_units)
            ),
            date_units AS (
                SELECT d.ds_date, u.unit_name
                FROM date_series d
                CROSS JOIN units u
            ),
            discharge_docs AS (
                SELECT encounter_id, MAX(created_at) AS completed_at
                FROM document
                WHERE document_type IN ('discharge_summary', 'patient_instructions')
                  AND UPPER(status) NOT IN ('DRAFT', 'REJECTED', 'CANCELLED')
                GROUP BY encounter_id
            ),
            -- Discharge metrics grouped by discharge date so admissions that
            -- occurred before the window but discharged inside it are counted.
            discharge_metrics AS (
                SELECT
                    DATE_TRUNC('day', e.discharge_date)::date AS metric_date,
                    UPPER(e.unit) AS unit_name,
                    COUNT(*) AS discharge_count,
                    AVG(EXTRACT(EPOCH FROM (dd.completed_at - e.created_at)) / 60.0)
                        FILTER (WHERE dd.completed_at IS NOT NULL) AS avg_discharge_doc_time_min,
                    COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1
                            FROM encounter e2
                            WHERE e2.patient_id = e.patient_id
                              AND e2.admit_date > e.discharge_date
                              AND e2.admit_date <= e.discharge_date + INTERVAL '30 days'
                              AND e2.deleted_at IS NULL
                        )
                    )::float / NULLIF(COUNT(*), 0) AS readmission_rate_30d,
                    COUNT(*) FILTER (
                        WHERE EXISTS (SELECT 1 FROM medication m WHERE m.encounter_id = e.id)
                          AND NOT EXISTS (
                              SELECT 1
                              FROM medication m
                              WHERE m.encounter_id = e.id
                                AND UPPER(m.reconciliation_status) != 'RECONCILED'
                          )
                    )::float / NULLIF(COUNT(*), 0) AS med_recon_completion_rate
                FROM encounter e
                LEFT JOIN discharge_docs dd ON dd.encounter_id = e.id
                WHERE e.deleted_at IS NULL
                  AND e.status = 'DISCHARGED'
                  AND e.discharge_date IS NOT NULL
                  AND e.discharge_date >= :from_date
                  AND e.discharge_date < :to_date + INTERVAL '1 day'
                  AND UPPER(e.unit) = ANY(:accessible_units)
                GROUP BY DATE_TRUNC('day', e.discharge_date)::date, UPPER(e.unit)
            ),
            -- Risk/census metrics grouped by admission date.
            admission_metrics AS (
                SELECT
                    DATE_TRUNC('day', e.admit_date)::date AS metric_date,
                    UPPER(e.unit) AS unit_name,
                    COUNT(*) FILTER (WHERE UPPER(e.risk_tier) = 'HIGH' OR e.risk_score > 0.7) AS high_risk_count,
                    COUNT(*) FILTER (WHERE UPPER(e.risk_tier) IN ('MEDIUM', 'MED')) AS medium_risk_count,
                    COUNT(*) FILTER (WHERE UPPER(e.risk_tier) = 'LOW') AS low_risk_count
                FROM encounter e
                WHERE e.deleted_at IS NULL
                  AND e.admit_date >= :from_date
                  AND e.admit_date < :to_date + INTERVAL '1 day'
                  AND UPPER(e.unit) = ANY(:accessible_units)
                GROUP BY DATE_TRUNC('day', e.admit_date)::date, UPPER(e.unit)
            ),
            task_metrics AS (
                SELECT
                    DATE_TRUNC('day', completed_at)::date AS metric_date,
                    UPPER(unit_id) AS unit_name,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'COMPLETED')::float
                        / NULLIF(COUNT(*), 0) AS agent_task_success_rate
                FROM agent_task
                WHERE completed_at IS NOT NULL
                  AND unit_id IS NOT NULL
                  AND UPPER(unit_id) = ANY(:accessible_units)
                GROUP BY DATE_TRUNC('day', completed_at)::date, UPPER(unit_id)
            ),
            bed_util AS (
                SELECT
                    UPPER(unit) AS unit_name,
                    COUNT(*) FILTER (WHERE UPPER(status) IN ('OCCUPIED', 'RESERVED'))::float
                        / NULLIF(COUNT(*), 0) * 100.0 AS bed_utilisation_pct
                FROM bed
                WHERE unit IS NOT NULL
                GROUP BY UPPER(unit)
            )
            SELECT
                du.ds_date AS date,
                du.unit_name AS unit,
                COALESCE(dm.discharge_count, 0) AS discharge_count,
                dm.avg_discharge_doc_time_min,
                COALESCE(dm.readmission_rate_30d, 0.0) AS readmission_rate_30d,
                COALESCE(dm.med_recon_completion_rate, 0.0) AS med_recon_completion_rate,
                COALESCE(bu.bed_utilisation_pct, 0.0) AS bed_utilisation_pct,
                COALESCE(tm.agent_task_success_rate, 0.0) AS agent_task_success_rate,
                COALESCE(am.high_risk_count, 0) AS high_risk_count,
                COALESCE(am.medium_risk_count, 0) AS medium_risk_count,
                COALESCE(am.low_risk_count, 0) AS low_risk_count
            FROM date_units du
            LEFT JOIN discharge_metrics dm
                   ON dm.metric_date = du.ds_date AND dm.unit_name = du.unit_name
            LEFT JOIN admission_metrics am
                   ON am.metric_date = du.ds_date AND am.unit_name = du.unit_name
            LEFT JOIN task_metrics tm
                   ON tm.metric_date = du.ds_date AND tm.unit_name = du.unit_name
            LEFT JOIN bed_util bu ON bu.unit_name = du.unit_name
            -- UNIT_FILTER_PLACEHOLDER
            ORDER BY du.ds_date ASC, du.unit_name ASC
            """
        )

        # Inline the optional unit filter safely (value is validated as a short string).
        unit_clause = "TRUE"
        if unit is not None:
            safe_unit = unit.replace("'", "''").upper()
            unit_clause = f"du.unit_name = '{safe_unit}'"
        query_text = sql.text.replace("-- UNIT_FILTER_PLACEHOLDER", f"WHERE {unit_clause}")
        sql = text(query_text)

        result = await self._session.execute(
            sql,
            {
                "from_date": from_date,
                "to_date": to_date,
                "accessible_units": [u.upper() for u in accessible_units],
            },
        )
        rows = result.mappings().all()

        data_points = [KpiDataPoint.model_validate(dict(row)) for row in rows]

        return KpiResponse(
            from_date=from_date,
            to_date=to_date,
            unit=unit,
            data=data_points,
            total_rows=len(data_points),
        )

    async def get_high_risk_encounters(
        self,
        accessible_units: list[str],
        unit: str | None = None,
        lookback_days: int = 7,
        limit: int = 10,
    ) -> HighRiskEncounterResponse:
        """Return the top N high-risk encounters discharged in the lookback window.

        Patient identifiers are masked so no PHI leaves the API.
        """
        if not accessible_units:
            return HighRiskEncounterResponse(
                as_of_date=datetime.date.today(),
                total_rows=0,
                data=[],
            )

        sql = text(
            """
            WITH high_risk AS (
                SELECT
                    e.id,
                    e.unit,
                    e.risk_score,
                    UPPER(e.risk_tier) AS risk_label,
                    e.discharge_date,
                    p.mrn_encrypted,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM scheduled_notification sn
                            WHERE sn.encounter_id = e.id
                              AND UPPER(sn.delivery_status::text) = 'DELIVERED'
                        ) THEN 'Completed'
                        WHEN EXISTS (
                            SELECT 1
                            FROM scheduled_notification sn
                            WHERE sn.encounter_id = e.id
                        ) THEN 'Scheduled'
                        ELSE 'Pending'
                    END AS follow_up_status
                FROM encounter e
                JOIN patient p ON p.id = e.patient_id
                WHERE e.deleted_at IS NULL
                  AND e.status = 'DISCHARGED'
                  AND e.discharge_date >= CURRENT_DATE - make_interval(days => :lookback_days)
                  AND (UPPER(e.risk_tier) = 'HIGH' OR e.risk_score > 0.7)
                  AND UPPER(e.unit) = ANY(:accessible_units)
                  -- UNIT_FILTER_PLACEHOLDER
                ORDER BY e.risk_score DESC NULLS LAST, e.discharge_date DESC
                LIMIT :limit
            )
            SELECT
                CASE
                    WHEN mrn_encrypted IS NULL THEN '***'
                    WHEN LENGTH(mrn_encrypted) <= 8 THEN '***' || mrn_encrypted
                    ELSE LEFT(mrn_encrypted, 3) || '***' || RIGHT(mrn_encrypted, 3)
                END AS patient_masked,
                unit,
                risk_score,
                risk_label,
                discharge_date::date AS discharge_date,
                follow_up_status
            FROM high_risk
            ORDER BY risk_score DESC NULLS LAST, discharge_date DESC
            """
        )

        # Inline the optional unit filter safely (value is validated as a short string).
        unit_clause = "TRUE"
        if unit is not None:
            safe_unit = unit.replace("'", "''").upper()
            unit_clause = f"UPPER(e.unit) = '{safe_unit}'"
        query_text = sql.text.replace("-- UNIT_FILTER_PLACEHOLDER", f"AND {unit_clause}")
        sql = text(query_text)

        result = await self._session.execute(
            sql,
            {
                "accessible_units": [u.upper() for u in accessible_units],
                "lookback_days": lookback_days,
                "limit": limit,
            },
        )
        rows = result.mappings().all()

        data = [HighRiskEncounter.model_validate(dict(row)) for row in rows]

        return HighRiskEncounterResponse(
            as_of_date=datetime.date.today(),
            total_rows=len(data),
            data=data,
        )
