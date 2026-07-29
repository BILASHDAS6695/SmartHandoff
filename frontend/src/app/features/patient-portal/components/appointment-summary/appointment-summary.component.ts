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
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Subject, takeUntil } from 'rxjs';
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
export class AppointmentSummaryComponent implements OnInit, OnDestroy {
  private readonly appointmentsService = inject(AppointmentsService);
  private readonly destroy$ = new Subject<void>();

  readonly appointments = signal<Appointment[]>([]);
  readonly isLoading = signal(true);
  readonly hasError = signal(false);

  ngOnInit(): void {
    this.appointmentsService
      .getAppointments()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
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

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
