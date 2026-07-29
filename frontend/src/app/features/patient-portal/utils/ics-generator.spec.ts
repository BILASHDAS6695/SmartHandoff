/**
 * Unit tests for ics-generator utilities.
 *
 * Coverage:
 *   US-055 DoD — .ics: BEGIN:VCALENDAR format with DTSTART:YYYYMMDDTHHMMSSZ
 *   US-055 DoD — SUMMARY:SmartHandoff Follow-up Appointment
 *   US-055 DoD — .ics download triggers Blob + anchor click
 */
import { generateIcsContent, downloadIcsFile } from './ics-generator';
import { Appointment } from '../models/appointment.model';

describe('generateIcsContent', () => {
  const mockAppointment: Appointment = {
    id: 'appt-123',
    type: 'Follow-up with your doctor',
    date: '2026-07-28',
    time: '10:30:00',
    provider: 'Dr. Smith',
    location: 'Cardiology Clinic, Floor 3',
  };

  it('should produce a string starting with BEGIN:VCALENDAR', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics.startsWith('BEGIN:VCALENDAR')).toBe(true);
  });

  it('should end with END:VCALENDAR', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics.trim().endsWith('END:VCALENDAR')).toBe(true);
  });

  it('should contain SUMMARY:SmartHandoff Follow-up Appointment', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics).toContain('SUMMARY:SmartHandoff Follow-up Appointment');
  });

  it('should contain DTSTART in YYYYMMDDTHHMMSSZ format for a timed appointment', () => {
    const ics = generateIcsContent(mockAppointment);
    // Expected: DTSTART:20260728T103000Z
    expect(ics).toContain('DTSTART:20260728T103000Z');
  });

  it('should default DTSTART to T090000Z when time is null', () => {
    const apptNoTime: Appointment = { ...mockAppointment, time: null };
    const ics = generateIcsContent(apptNoTime);
    expect(ics).toContain('DTSTART:20260728T090000Z');
  });

  it('should contain BEGIN:VEVENT and END:VEVENT', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics).toContain('BEGIN:VEVENT');
    expect(ics).toContain('END:VEVENT');
  });

  it('should use \\r\\n line endings (RFC 5545 compliance)', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics).toContain('\r\n');
  });
});

describe('downloadIcsFile', () => {
  const mockAppointment: Appointment = {
    id: 'appt-456',
    type: 'Follow-up with your doctor',
    date: '2026-07-28',
    time: '09:00:00',
    provider: null,
    location: null,
  };

  it('should create an anchor element and trigger click', () => {
    // Mock URL.createObjectURL before the test
    const mockUrl = 'blob:mock-url';
    (URL as any).createObjectURL = jest.fn(() => mockUrl);
    (URL as any).revokeObjectURL = jest.fn();

    // Track if click was called
    const clickSpy = jest.fn();
    const originalCreateElement = document.createElement;
    jest.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'a') {
        const el = originalCreateElement.call(document, tag);
        el.click = clickSpy;
        return el as any;
      }
      return originalCreateElement.call(document, tag);
    });

    downloadIcsFile(mockAppointment);

    // Verify click was triggered
    expect(clickSpy).toHaveBeenCalled();
    expect((URL as any).createObjectURL).toHaveBeenCalled();
    
    jest.restoreAllMocks();
  });
});
