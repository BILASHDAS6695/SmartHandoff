import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { BedDto, BED_STATUS_CLASS } from '../../models/bed.model';
import { MaskNamePipe } from '@shared/pipes/mask-name.pipe';

/**
 * BedCellComponent — Atomic bed cell component rendered within BedBoardComponent grid.
 * Displays bed status with colour-coded background, patient name (initials), and predicted discharge time.
 * Complies with WCAG 2.2 Level AA via aria-label (US-050 AC5, TASK-004).
 * @component
 * @example
 * <app-bed-cell [bed]="bedDto" (click)="onBedClick(bedDto)"></app-bed-cell>
 */
@Component({
  selector: 'app-bed-cell',
  standalone: true,
  imports: [CommonModule, MatCardModule, MaskNamePipe],
  templateUrl: './bed-cell.component.html',
  styleUrl: './bed-cell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedCellComponent {
  @Input({ required: true }) bed!: BedDto;

  /**
   * Returns CSS class name for bed status colour (green/blue/orange/grey/purple).
   * Maps BedStatus enum value to colour token class (US-050 AC2).
   */
  get statusClass(): string {
    return BED_STATUS_CLASS[this.bed.status];
  }

  /**
   * Generates accessible label for screen readers and browser tools.
   * Format: "Bed 3A-02, status Occupied, patient J.D., discharge predicted 3:00 PM"
   * Complies with WCAG 2.2 Level AA accessibility requirements (US-050 TASK-004 AC5).
   */
  get ariaLabel(): string {
    const status = this.bed.status.charAt(0) + this.bed.status.slice(1).toLowerCase();
    const patient = this.bed.patientName
      ? `, patient ${new MaskNamePipe().transform(this.bed.patientName)}`
      : '';
    const discharge = this.bed.predictedDischargeTime
      ? `, discharge predicted ${new Date(this.bed.predictedDischargeTime)
          .toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
      : '';
    return `Bed ${this.bed.bedId}, status ${status}${patient}${discharge}`;
  }
}
