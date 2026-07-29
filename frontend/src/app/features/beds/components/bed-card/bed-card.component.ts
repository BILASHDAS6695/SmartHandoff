/**
 * BedCardComponent — displays a single bed card with status, occupancy, and predicted discharge.
 *
 * Design refs:
 *   US-035 — Bed status display
 *   US-036 — Predicted discharge time display
 */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { BedItem } from '../../models/bed.model';
import { DischargeWindowComponent } from '../discharge-window/discharge-window.component';

@Component({
  selector: 'sh-bed-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    MatCardModule,
    MatIconModule,
    MatChipsModule,
    DischargeWindowComponent,
  ],
  template: `
    <mat-card class="bed-card" [class.bed-card--occupied]="bed.bedStatus === 'OCCUPIED'">
      <mat-card-header>
        <mat-card-title>{{ bed.unit }} - {{ bed.room }} - {{ bed.bedNumber }}</mat-card-title>
        <mat-chip [class]="'bed-status bed-status--' + bed.bedStatus.toLowerCase()">
          {{ bed.bedStatus }}
        </mat-chip>
      </mat-card-header>
      <mat-card-content>
        @if (bed.bedStatus === 'OCCUPIED' && bed.encounterId) {
          <div class="bed-card__encounter">
            <p class="bed-card__encounter-id">Encounter: {{ bed.encounterId }}</p>
            <!-- US-036: Show prediction only for OCCUPIED beds -->
            <sh-discharge-window
              [predictedDischargeTime]="bed.predictedDischargeTime"
              [dischargePredictionConfidence]="bed.dischargePredictionConfidence"
              [intervalHours]="bed.dischargePredictionIntervalHours"
            />
          </div>
        }
        @if (bed.bedStatus === 'VACANT') {
          <p class="bed-card__status-text">Available for admission</p>
        }
        @if (bed.bedStatus === 'DIRTY') {
          <p class="bed-card__status-text">Awaiting housekeeping</p>
        }
        @if (bed.bedStatus === 'MAINTENANCE') {
          <p class="bed-card__status-text">Under maintenance</p>
        }
      </mat-card-content>
    </mat-card>
  `,
  styles: [`
    .bed-card {
      margin: 8px;
      transition: box-shadow 0.2s;
    }
    .bed-card--occupied {
      border-left: 4px solid #2e7d32;
    }
    .bed-card__encounter {
      margin-top: 8px;
    }
    .bed-card__encounter-id {
      font-size: 0.75rem;
      color: var(--mat-sys-on-surface-variant);
      margin-bottom: 8px;
    }
    .bed-card__status-text {
      font-size: 0.875rem;
      color: var(--mat-sys-on-surface-variant);
    }
    .bed-status {
      font-size: 0.75rem;
      font-weight: 500;
    }
    .bed-status--occupied { background-color: #2e7d32; color: #fff; }
    .bed-status--vacant { background-color: #1976d2; color: #fff; }
    .bed-status--dirty { background-color: #f57f17; color: #fff; }
    .bed-status--maintenance { background-color: #757575; color: #fff; }
  `],
})
export class BedCardComponent {
  @Input({ required: true }) bed!: BedItem;
}
