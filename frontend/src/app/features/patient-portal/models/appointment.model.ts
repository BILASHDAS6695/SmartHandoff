/**
 * Appointment domain models for the patient portal.
 *
 * Design refs:
 *   US-055 AC Scenario 2 — fields: appointment type, date, time, calendar-add button
 *   US-040               — GET /api/v1/patients/{id}/appointments response shape
 */

export interface Appointment {
  id: string;
  type: string;           // e.g. "Follow-up with your doctor"
  date: string;           // ISO 8601 date: "2026-07-21"
  time: string | null;    // ISO 8601 time: "09:30:00" or null if unscheduled
  provider: string | null;
  location: string | null;
}

export interface AppointmentListResponse {
  appointments: Appointment[];
}
