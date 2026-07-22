"""HL7 v2.x ADT message parser — extracts a typed ADTEvent from raw HL7 text.

Responsibilities:
  1. Validate mandatory segment presence (MSH, EVN, PID; PV1 for A01/A02/A03).
  2. Classify the trigger event code (MSH-9.2) via HL7_TRIGGER_MAP.
  3. Extract all required fields from MSH, EVN, PID, PV1, PV2, DG1.
  4. Return a fully validated ``ADTEvent`` Pydantic object.

Raises:
  HL7ValidationError — for missing mandatory segments, unknown event types,
                       or mandatory field extraction failures.

hl7apy usage:
  - ``VALIDATION_LEVEL.QUIET`` — returns empty string for missing optional
    fields instead of raising; keeps parsing tolerant of EHR variations.

PID-3 MRN extraction (Technical Notes):
  PID-3 is a repeating CX field. Iterate repetitions; pick the first where
  CX-5 (identifier type code) == ``"MR"``. Fall back to PID-3[0] if no typed
  ``MR`` repetition exists.

DG1 multi-segment:
  hl7apy exposes repeated DG1 segments via ``msg.children``.  Filter by name
  ``"DG1"`` and extract ``DG1-3.1`` (CWE component 1 = code) from each.

Design refs:
    FR-002   — ADT event type classification (A01–A13)
    FR-003   — HL7 message validation: mandatory segments, field extraction
    AIR-002  — Mandatory: MSH, EVN, PID; PV1 for A01/A02/A03
    DR-022   — Idempotency: MSH-10 stored as source_message_id
    US-012   — DoD: HL7Parser with all 15+ field extractions
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from hl7apy.core import Message  # type: ignore[import]
from hl7apy.exceptions import ValidationError as Hl7apyValidationError  # type: ignore[import]
from hl7apy import VALIDATION_LEVEL  # type: ignore[import]

from app.parser.models import (
    ADTEvent,
    EventType,
    HL7ValidationError,
    HL7_TRIGGER_MAP,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types that require PV1 as mandatory (AIR-002)
# ---------------------------------------------------------------------------

_PV1_REQUIRED_TRIGGERS: frozenset[str] = frozenset({"A01", "A02", "A03"})

# ---------------------------------------------------------------------------
# DTM format helpers
# ---------------------------------------------------------------------------

_DTM_FORMATS = [
    ("%Y%m%d%H%M%S", 14),  # YYYYMMDDHHMMSS
    ("%Y%m%d%H%M", 12),    # YYYYMMDDHHMM
    ("%Y%m%d", 8),          # YYYYMMDD
]


def _parse_dtm(value: str, field_ref: str) -> datetime.datetime:
    """Parse an HL7 DTM string to a UTC-aware datetime.

    Tries formats from most specific to least specific.
    Raises ``HL7ValidationError`` if no format matches.
    """
    value = value.strip()
    for fmt, length in _DTM_FORMATS:
        try:
            dt = datetime.datetime.strptime(value[:length], fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise HL7ValidationError(
        f"Cannot parse DTM value '{value}' in field {field_ref}",
        field=field_ref,
    )


def _parse_date(value: str, field_ref: str) -> Optional[datetime.date]:
    """Parse an HL7 date string (YYYYMMDD) to a date. Returns None if blank."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        logger.warning("Cannot parse date value in field %s — skipping", field_ref)
        return None


def _safe_value(component, field_ref: str) -> str:  # type: ignore[type-arg]
    """Return the ``.value`` of an hl7apy component/field, or empty string on error."""
    try:
        val = component.value
        return val.strip() if val else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# HL7Parser
# ---------------------------------------------------------------------------

class HL7Parser:
    """Parses a raw HL7 v2.x ADT message string into a typed ``ADTEvent``.

    Usage::

        parser = HL7Parser()
        event = parser.parse(raw_hl7_string)

    The parser is stateless and thread-safe; a single instance may be reused
    across multiple ``parse()`` calls.
    """

    def parse(self, raw_hl7: str) -> ADTEvent:
        """Parse a raw HL7 string and return a validated ``ADTEvent``.

        Args:
            raw_hl7: Raw HL7 v2.x text (CR-terminated segments, no MLLP framing).

        Returns:
            A fully populated ``ADTEvent`` instance.

        Raises:
            HL7ValidationError: If mandatory segments are absent, the trigger
                event code is not in the supported set, or a mandatory field
                cannot be extracted.
        """
        try:
            msg = Message(raw_hl7, validation_level=VALIDATION_LEVEL.QUIET)
        except (Hl7apyValidationError, Exception) as exc:
            raise HL7ValidationError(
                f"hl7apy failed to parse message: {exc}",
                segment="MSH",
            ) from exc

        # -- 2. Validate mandatory segments ------------------------------------
        self._validate_mandatory_segments(msg, raw_hl7)

        # -- 3. Extract MSH fields ---------------------------------------------
        trigger_code = self._extract_trigger_code(msg)
        event_type = self._resolve_event_type(trigger_code)

        source_message_id = _safe_value(msg.msh.msh_10, "MSH-10")
        if not source_message_id:
            raise HL7ValidationError(
                "MSH-10 (message control ID) is empty — required for idempotency",
                segment="MSH",
                field="MSH-10",
            )
        sending_application = _safe_value(msg.msh.msh_3, "MSH-3")
        message_datetime = _parse_dtm(
            _safe_value(msg.msh.msh_7, "MSH-7"), "MSH-7"
        )

        # -- 4. Extract EVN-2 --------------------------------------------------
        event_time = _parse_dtm(_safe_value(msg.evn.evn_2, "EVN-2"), "EVN-2")

        # -- 5. Extract PID fields ---------------------------------------------
        patient_mrn = self._extract_mrn(msg)
        patient_last_name = _safe_value(msg.pid.pid_5.pid_5_1, "PID-5.1") or None
        patient_first_name = _safe_value(msg.pid.pid_5.pid_5_2, "PID-5.2") or None
        patient_dob = _parse_date(_safe_value(msg.pid.pid_7, "PID-7"), "PID-7")
        patient_address = _safe_value(msg.pid.pid_11.pid_11_1, "PID-11.1") or None

        # -- 6. Extract PV1 fields (optional for A04/A08/cancels) --------------
        (
            encounter_id,
            patient_class,
            assigned_location,
            attending_provider,
            patient_type,
        ) = self._extract_pv1_fields(msg, trigger_code)

        # -- 7. Extract PV2-3 (optional) ----------------------------------------
        admit_reason = self._extract_admit_reason(msg)

        # -- 8. Extract DG1 diagnoses (repeating segment) ----------------------
        diagnoses = self._extract_diagnoses(msg)

        # -- 9. Build and return ADTEvent --------------------------------------
        return ADTEvent(
            source_message_id=source_message_id,
            event_type=event_type,
            sending_application=sending_application,
            message_datetime=message_datetime,
            event_time=event_time,
            patient_mrn=patient_mrn,
            patient_last_name=patient_last_name,
            patient_first_name=patient_first_name,
            patient_dob=patient_dob,
            patient_address=patient_address,
            encounter_id=encounter_id,
            patient_class=patient_class,
            assigned_location=assigned_location,
            attending_provider=attending_provider,
            patient_type=patient_type,
            admit_reason=admit_reason,
            diagnoses=diagnoses,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_mandatory_segments(self, msg: Message, raw_hl7: str) -> None:
        """Raise HL7ValidationError if MSH, EVN, or PID are absent.

        PV1 is additionally required for trigger codes A01, A02, A03 (AIR-002).
        """
        segment_names = {seg.name for seg in msg.children}  # type: ignore[attr-defined]

        for required in ("MSH", "EVN", "PID"):
            if required not in segment_names:
                raise HL7ValidationError(
                    f"Mandatory segment '{required}' is absent from the HL7 message",
                    segment=required,
                )

        # PV1 required for admission, transfer, discharge events
        trigger_raw = ""
        try:
            trigger_raw = _safe_value(msg.msh.msh_9.msh_9_2, "MSH-9.2")  # type: ignore[attr-defined]
        except Exception:
            pass

        if trigger_raw in _PV1_REQUIRED_TRIGGERS and "PV1" not in segment_names:
            raise HL7ValidationError(
                f"Mandatory segment 'PV1' is absent for trigger event {trigger_raw}",
                segment="PV1",
            )

    def _extract_trigger_code(self, msg: Message) -> str:
        """Extract and normalise the MSH-9.2 trigger event code."""
        try:
            code = _safe_value(msg.msh.msh_9.msh_9_2, "MSH-9.2")  # type: ignore[attr-defined]
        except Exception as exc:
            raise HL7ValidationError(
                f"Cannot read MSH-9 (message type/trigger event): {exc}",
                segment="MSH",
                field="MSH-9",
            ) from exc

        if not code:
            # Fallback: try MSH-9 composite value and split
            try:
                msh9 = _safe_value(msg.msh.msh_9, "MSH-9")  # type: ignore[attr-defined]
                if "^" in msh9:
                    code = msh9.split("^")[1]
            except Exception:
                pass

        if not code:
            raise HL7ValidationError(
                "MSH-9.2 (trigger event code) is empty",
                segment="MSH",
                field="MSH-9.2",
            )
        return code.upper()

    def _resolve_event_type(self, trigger_code: str) -> EventType:
        """Map an HL7 trigger code to EventType; raise HL7ValidationError if unknown."""
        event_type = HL7_TRIGGER_MAP.get(trigger_code)
        if event_type is None:
            raise HL7ValidationError(
                f"Unknown or unsupported HL7 trigger event code: '{trigger_code}'",
                segment="MSH",
                field="MSH-9.2",
            )
        return event_type

    def _extract_mrn(self, msg: Message) -> str:
        """Extract patient MRN from PID-3 (first CX repetition with type 'MR').

        Per Technical Notes: iterate PID-3 repetitions; pick first where CX-5
        (identifier type code) == 'MR'. Fall back to first repetition if none
        is typed 'MR'.
        """
        try:
            pid3_reps = msg.pid.pid_3  # type: ignore[attr-defined]
        except Exception as exc:
            raise HL7ValidationError(
                f"Cannot access PID-3 (patient identifier list): {exc}",
                segment="PID",
                field="PID-3",
            ) from exc

        # Normalise to list (hl7apy may return single field or list)
        if not isinstance(pid3_reps, list):
            pid3_reps = [pid3_reps]

        mrn: Optional[str] = None
        fallback: Optional[str] = None

        for rep in pid3_reps:
            try:
                id_value = _safe_value(rep.cx_1, "PID-3.1")
                id_type = _safe_value(rep.cx_5, "PID-3.5")
            except Exception:
                id_value = _safe_value(rep, "PID-3")
                id_type = ""

            if fallback is None and id_value:
                fallback = id_value

            if id_type == "MR" and id_value:
                mrn = id_value
                break

        result = mrn or fallback
        if not result:
            raise HL7ValidationError(
                "PID-3 (patient identifier list) is empty or MRN cannot be extracted",
                segment="PID",
                field="PID-3",
            )
        return result

    def _extract_pv1_fields(
        self,
        msg: Message,
        trigger_code: str,
    ) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extract PV1 fields. Returns (encounter_id, patient_class,
        assigned_location, attending_provider, patient_type).

        PV1 is optional for A04, A08, A11, A12, A13; returns empty/None for
        those event types when the segment is absent.
        """
        try:
            pv1 = msg.pv1  # type: ignore[attr-defined]
        except Exception:
            if trigger_code in _PV1_REQUIRED_TRIGGERS:
                raise HL7ValidationError(
                    f"PV1 segment required for trigger {trigger_code} but not accessible",
                    segment="PV1",
                )
            return ("", None, None, None, None)

        encounter_id = _safe_value(pv1.pv1_19, "PV1-19")
        if not encounter_id and trigger_code in _PV1_REQUIRED_TRIGGERS:
            raise HL7ValidationError(
                "PV1-19 (visit number/encounter ID) is empty",
                segment="PV1",
                field="PV1-19",
            )

        patient_class = _safe_value(pv1.pv1_2, "PV1-2") or None
        assigned_location = _safe_value(pv1.pv1_3, "PV1-3") or None
        attending_provider = _safe_value(pv1.pv1_7, "PV1-7") or None
        patient_type = _safe_value(pv1.pv1_18, "PV1-18") or None

        return encounter_id, patient_class, assigned_location, attending_provider, patient_type

    def _extract_admit_reason(self, msg: Message) -> Optional[str]:
        """Extract PV2-3 (admit reason text). Returns None if PV2 absent."""
        try:
            return _safe_value(msg.pv2.pv2_3, "PV2-3") or None  # type: ignore[attr-defined]
        except Exception:
            return None

    def _extract_diagnoses(self, msg: Message) -> list[str]:
        """Extract all DG1-3 diagnosis codes (DG1 may repeat).

        Iterates all child segments named 'DG1' and extracts the CWE code
        component (DG1-3.1) from each.
        """
        diagnoses: list[str] = []
        try:
            dg1_segments = [seg for seg in msg.children if seg.name == "DG1"]  # type: ignore[attr-defined]
        except Exception:
            return diagnoses

        for dg1 in dg1_segments:
            try:
                code = _safe_value(dg1.dg1_3.dg1_3_1, "DG1-3.1")
                if code:
                    diagnoses.append(code)
            except Exception:
                logger.debug("Could not extract DG1-3 code from DG1 segment — skipping")

        return diagnoses
