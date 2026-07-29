/**
 * AppointmentsService — fetches upcoming follow-up appointments for the patient.
 *
 * Authentication: patient JWT injected automatically by JwtInterceptor.
 * patient_id is extracted from the JWT claim via AuthService.
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
import { AuthService } from '../../../core/auth/auth.service';
import { Appointment, AppointmentListResponse } from '../models/appointment.model';

@Injectable({ providedIn: 'root' })
export class AppointmentsService {
  private readonly http = inject(HttpClient);
  private readonly authService = inject(AuthService);
  private readonly baseUrl = environment.apiBaseUrl;

  /**
   * Fetch all upcoming appointments for the authenticated patient.
   * patient_id sourced from JWT — never passed by the caller.
   */
  getAppointments(): Observable<Appointment[]> {
    const patientId = this.authService.getPatientClaim<string>('patient_id');
    if (!patientId) {
      throw new Error('patient_id not found in JWT claims');
    }
    return this.http
      .get<AppointmentListResponse>(
        `${this.baseUrl}/api/v1/patients/${patientId}/appointments`
      )
      .pipe(map(response => response.appointments));
  }
}
