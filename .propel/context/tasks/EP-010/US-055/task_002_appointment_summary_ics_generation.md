---
id: TASK-002
title: "AppointmentSummaryComponent — Appointment List Display & .ics Calendar File Generation"
user_story: US-055
epic: EP-010
sprint: 2
layer: Frontend
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-052, US-040]
---

# TASK-002: AppointmentSummaryComponent — Appointment List Display & .ics Calendar File Generation

> **Story:** US-055 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-055 requires an `AppointmentSummaryComponent` in the patient portal that:

1. Fetches upcoming follow-up appointments from `GET /api/v1/patients/{id}/appointments` using the patient JWT
2. Displays each appointment with: appointment type ("Follow-up with your doctor"), date, time (if set), and a calendar-add button
3. Generates a `.ics` (iCalendar) file on demand for the calendar-add button — file must conform to `BEGIN:VCALENDAR` / VEVENT format with `DTSTART:YYYYMMDDTHHMMSSZ` and `SUMMARY:SmartHandoff Follow-up Appointment`
4. Patient ID is extracted from the JWT claim via `PatientAuthService`

**Design references:**
- design.md §3.4 — `features/patient-portal/` lazy-loaded module
- design.md §4.1 — Angular 17, Angular Material
- US-055 AC Scenario 2 — "Your Appointments" section; HIGH-risk follow-up visible; calendar-add button downloads .ics
- US-055 Technical Notes — `.ics` format: `DTSTART:YYYYMMDDTHHMMSSZ`, `SUMMARY:SmartHandoff Follow-up Appointment`
- US-040 — Follow-up appointments API (`GET /api/v1/patients/{id}/appointments`)
- US-052 — Patient JWT with `patient_id` and `encounter_id` claims

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | "Your Appointments" section lists type, date, time, calendar-add button; .ics file downloadable |

---

## Implementation Steps

### 1. Scaffold component and service files

```bash
mkdir -p frontend/src/app/features/patient-portal/components/appointment-summary
touch frontend/src/app/features/patient-portal/components/appointment-summary/appointment-summary.component.ts
touch frontend/src/app/features/patient-portal/components/appointment-summary/appointment-summary.component.html
touch frontend/src/app/features/patient-portal/components/appointment-summary/appointment-summary.component.scss
touch frontend/src/app/features/patient-portal/services/appointments.service.ts
touch frontend/src/app/features/patient-portal/models/appointment.model.ts
touch frontend/src/app/features/patient-portal/utils/ics-generator.ts
```

### 2. Define `frontend/src/app/features/patient-portal/models/appointment.model.ts`

```typescript
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
```

### 3. Implement `.ics` generator utility

**File:** `frontend/src/app/features/patient-portal/utils/ics-generator.ts`

```typescript
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
```

### 4. Implement `appointments.service.ts`

```typescript
/**
 * AppointmentsService — fetches upcoming follow-up appointments for the patient.
 *
 * Authentication: patient JWT injected automatically by JwtInterceptor.
 * patient_id is extracted from the JWT claim via PatientAuthService.
 *
 * Design refs:
 *   US-055 AC Scenario 2 — GET /api/v1/patients/{id}/appointments
 *   US-040               — Follow-up appointments API backend
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { environment } from '../../../../environments/environment';
import { PatientAuthService } from '../../auth/services/patient-auth.service';
import { Appointment, AppointmentListResponse } from '../models/appointment.model';

@Injectable({ providedIn: 'root' })
export class AppointmentsService {
  private readonly http = inject(HttpClient);
  private readonly patientAuth = inject(PatientAuthService);
  private readonly baseUrl = environment.apiBaseUrl;

  /**
   * Fetch all upcoming appointments for the authenticated patient.
   * patient_id sourced from JWT — never passed by the caller.
   */
  getAppointments(): Observable<Appointment[]> {
    const patientId = this.patientAuth.getPatientId();
    return this.http
      .get<AppointmentListResponse>(`${this.baseUrl}/api/v1/patients/${patientId}/appointments`)
      .pipe(map(res => res.appointments));
  }
}
```

### 5. Implement `appointment-summary.component.ts`

```typescript
/**
 * AppointmentSummaryComponent — lists upcoming follow-up appointments with .ics download.
 *
 * Design refs:
 *   US-055 AC Scenario 2   — appointment type, date, time, calendar-add button
 *   US-055 Technical Notes — .ics: BEGIN:VCALENDAR format
 *   ADR-005                — Angular 17 standalone components
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { AppointmentsService } from '../../services/appointments.service';
import { Appointment } from '../../models/appointment.model';
import { downloadIcsFile } from '../../utils/ics-generator';

@Component({
  selector: 'app-appointment-summary',
  standalone: true,
  imports: [
    CommonModule,
    DatePipe,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './appointment-summary.component.html',
  styleUrls: ['./appointment-summary.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppointmentSummaryComponent implements OnInit {
  private readonly appointmentsService = inject(AppointmentsService);

  readonly appointments = signal<Appointment[]>([]);
  readonly isLoading = signal(true);
  readonly hasError = signal(false);

  ngOnInit(): void {
    this.appointmentsService.getAppointments().subscribe({
      next: (appts) => {
        this.appointments.set(appts);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  downloadCalendar(appointment: Appointment): void {
    downloadIcsFile(appointment);
  }
}
```

### 6. Implement `appointment-summary.component.html`

```html
<!-- AppointmentSummaryComponent
     US-055 AC Scenario 2: type, date, time, calendar-add button per appointment
-->
<section class="appointment-summary" aria-labelledby="appointments-heading">
  <h2 id="appointments-heading" class="appointments-title">Your Appointments</h2>

  @if (isLoading()) {
    <mat-spinner diameter="40" aria-label="Loading appointments"></mat-spinner>
  } @else if (hasError()) {
    <p class="appointments-error" role="alert">
      Unable to load appointments. Please refresh the page or contact your care team.
    </p>
  } @else if (appointments().length === 0) {
    <p class="appointments-empty">No upcoming appointments scheduled.</p>
  } @else {
    <ul class="appointment-list" role="list">
      @for (appt of appointments(); track appt.id) {
        <li class="appointment-card" role="listitem">
          <mat-card>
            <mat-card-content>
              <div class="appt-type">
                <mat-icon aria-hidden="true">event</mat-icon>
                <span>{{ appt.type }}</span>
              </div>
              <p class="appt-date">
                <strong>Date:</strong> {{ appt.date | date:'fullDate' }}
              </p>
              @if (appt.time) {
                <p class="appt-time">
                  <strong>Time:</strong> {{ appt.time | date:'shortTime':'UTC' }}
                </p>
              }
              @if (appt.provider) {
                <p class="appt-provider">
                  <strong>Provider:</strong> {{ appt.provider }}
                </p>
              }
            </mat-card-content>
            <mat-card-actions>
              <button
                mat-stroked-button
                color="primary"
                (click)="downloadCalendar(appt)"
                aria-label="Add {{ appt.type }} on {{ appt.date }} to calendar">
                <mat-icon>calendar_today</mat-icon>
                Add to Calendar
              </button>
            </mat-card-actions>
          </mat-card>
        </li>
      }
    </ul>
  }
</section>
```

### 7. Implement `appointment-summary.component.scss`

```scss
// AppointmentSummaryComponent styles
// US-055 DoD: mobile-friendly layout

.appointment-summary {
  padding: 16px;
}

.appointments-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 16px;
  color: #1565c0;
}

.appointment-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.appointment-card {
  mat-card {
    border-radius: 8px;
  }
}

.appt-type {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 8px;
  color: #212121;
}

.appt-date,
.appt-time,
.appt-provider {
  font-size: 14px;
  margin: 4px 0;
  color: #424242;
}

.appointments-error {
  color: #c62828;
  font-size: 14px;
}

.appointments-empty {
  color: #616161;
  font-size: 14px;
}
```

### 8. Register `AppointmentSummaryComponent` in `PatientPortalModule`

In `frontend/src/app/features/patient-portal/patient-portal.module.ts`:

```typescript
import { AppointmentSummaryComponent } from './components/appointment-summary/appointment-summary.component';

// Inside @NgModule imports:
imports: [
  // ...existing imports
  AppointmentSummaryComponent,
],
```

Embed in portal shell template before the chatbot widget:

```html
<!-- patient-portal.component.html -->
<app-appointment-summary></app-appointment-summary>
<app-chatbot-widget></app-chatbot-widget>
```

---

## Validation Checklist

```
[ ] "Your Appointments" heading visible in patient portal
[ ] Loading spinner displayed while API call is in-flight
[ ] Each appointment card shows: type, date, time (if set), provider (if set)
[ ] "Add to Calendar" button visible on each appointment card
[ ] Clicking "Add to Calendar" triggers .ics file download in browser
[ ] .ics file opens in calendar app (macOS Calendar / Google Calendar / Outlook)
[ ] .ics SUMMARY field reads "SmartHandoff Follow-up Appointment"
[ ] .ics DTSTART format matches YYYYMMDDTHHMMSSZ (e.g. 20260721T090000Z)
[ ] Empty state message shown when no appointments returned
[ ] Error state message shown when API call fails
[ ] Mobile viewport: cards stack vertically, no horizontal overflow
[ ] network tab: GET /api/v1/patients/{id}/appointments called with patient JWT
[ ] Angular strict mode passes — no 'any' types
[ ] WCAG 2.2 AA: aria-label on calendar button includes appointment type and date
```

---

## Definition of Done Mapping

| DoD Item | Covered |
|---|---|
| `AppointmentSummaryComponent`: lists appointments from `GET /api/v1/patients/{id}/appointments` | ✅ This task |
| `.ics` calendar file generation: `BEGIN:VCALENDAR` format with appointment details | ✅ This task |
