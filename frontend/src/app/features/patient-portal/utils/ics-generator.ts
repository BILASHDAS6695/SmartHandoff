/**
 * Generates an RFC 5545-compliant iCalendar (.ics) file string for a single appointment.
 *
 * Format specification:
 *   US-055 Technical Notes — DTSTART:YYYYMMDDTHHMMSSZ; SUMMARY:SmartHandoff Follow-up Appointment
 *   RFC 5545 §3.6.1       — VEVENT component
 *
 * @param appointment - The appointment to encode
 * @returns  Raw .ics file content as a string
 */
import { Appointment } from '../models/appointment.model';

export function generateIcsContent(appointment: Appointment): string {
  const dtStart = formatIcsDateTime(appointment.date, appointment.time);
  // Default duration: 30 minutes when no explicit end time is set
  const dtEnd = formatIcsDateTimeOffset(appointment.date, appointment.time, 30);
  const uid = `smarthandoff-appt-${appointment.id}@smarthandoff.app`;
  const now = formatIcsDateTime(new Date().toISOString().split('T')[0], new Date().toISOString().split('T')[1].split('.')[0]);

  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//SmartHandoff//PatientPortal//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${now}`,
    `DTSTART:${dtStart}`,
    `DTEND:${dtEnd}`,
    'SUMMARY:SmartHandoff Follow-up Appointment',
    `DESCRIPTION:${appointment.type}${appointment.provider ? ` with ${appointment.provider}` : ''}`,
    `LOCATION:${appointment.location ?? 'To be confirmed'}`,
    'END:VEVENT',
    'END:VCALENDAR',
  ].join('\r\n');
}

/**
 * Formats date + optional time into YYYYMMDDTHHMMSSZ for .ics DTSTART.
 * When time is null, defaults to T090000Z (9:00 AM UTC).
 */
function formatIcsDateTime(date: string, time: string | null): string {
  const [year, month, day] = date.split('-');
  const [hh, mm, ss] = (time ?? '09:00:00').split(':');
  return `${year}${month}${day}T${hh}${mm}${ss ?? '00'}Z`;
}

/**
 * Returns DTEND by adding `minutesOffset` to the start time.
 */
function formatIcsDateTimeOffset(date: string, time: string | null, minutesOffset: number): string {
  const [year, month, day] = date.split('-');
  const [hh, mm] = (time ?? '09:00:00').split(':');
  const startMinutes = parseInt(hh, 10) * 60 + parseInt(mm, 10);
  const endMinutes = startMinutes + minutesOffset;
  const endHh = String(Math.floor(endMinutes / 60) % 24).padStart(2, '0');
  const endMm = String(endMinutes % 60).padStart(2, '0');
  return `${year}${month}${day}T${endHh}${endMm}00Z`;
}

/**
 * Triggers a browser download of the .ics content as a file.
 */
export function downloadIcsFile(appointment: Appointment): void {
  const content = generateIcsContent(appointment);
  const blob = new Blob([content], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `smarthandoff-followup-${appointment.id}.ics`;
  anchor.click();
  URL.revokeObjectURL(url);
}
