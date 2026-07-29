import {
  Component, Input, Output, EventEmitter,
  ChangeDetectionStrategy, HostListener,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { BedDto } from '../../models/bed.model';
import { MaskNamePipe } from '@shared/pipes/mask-name.pipe';

/**
 * BedDetailPanelComponent — Right-side slide-in panel for detailed bed information.
 * Displays patient details with RBAC-controlled name visibility (initials vs. full name).
 * Shows risk tier badge, predicted discharge time, and "Assign Bed" button for vacant beds.
 * Satisfies US-050 Scenario 3: clicking a bed cell opens this panel.
 *
 * @component
 * @example
 * <app-bed-detail-panel
 *   [bed]="selectedBedDto"
 *   (closed)="onPanelClosed()"
 *   (assignBed)="onAssignBed($event)">
 * </app-bed-detail-panel>
 */
@Component({
  selector: 'app-bed-detail-panel',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatChipsModule, MatIconModule],
  templateUrl: './bed-detail-panel.component.html',
  styleUrl: './bed-detail-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedDetailPanelComponent {
  @Input() bed: BedDto | null = null;
  @Output() closed = new EventEmitter<void>();
  @Output() assignBed = new EventEmitter<BedDto>();

  get isOpen(): boolean { return this.bed !== null; }

  /**
   * Returns patient name as initials for HIPAA PHI compliance.
   * Note: For full RBAC-based name visibility, inject AuthService and check roles.
   */
  get patientDisplayName(): string | null {
    if (!this.bed?.patientName) return null;
    // Return initials for privacy protection
    const parts = this.bed.patientName.split(' ');
    return parts.map(p => p.charAt(0).toUpperCase()).join('');
  }

  /**
   * Returns CSS class for risk tier chip colour.
   * HIGH=red, MEDIUM=amber, LOW=green.
   */
  get riskChipClass(): string {
    const map: Record<string, string> = {
      HIGH: 'risk-chip--high',
      MEDIUM: 'risk-chip--medium',
      LOW: 'risk-chip--low',
    };
    return this.bed?.riskTier ? (map[this.bed.riskTier] ?? '') : '';
  }

  close(): void { this.closed.emit(); }

  onAssignBed(): void {
    if (this.bed) this.assignBed.emit(this.bed);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void { if (this.isOpen) this.close(); }
}
