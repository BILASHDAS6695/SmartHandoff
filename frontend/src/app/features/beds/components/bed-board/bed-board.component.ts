import { Component, OnInit, signal, inject, ChangeDetectionStrategy, OnDestroy, computed, CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { BedBoardService } from '../../services/bed-board.service';
import { BedRealtimeService } from '../../services/bed-realtime.service';
import { BedCellComponent } from '../bed-cell/bed-cell.component';
import { BedDetailPanelComponent } from '../bed-detail-panel/bed-detail-panel.component';
import { BedDto, BedUpdateEvent } from '../../models/bed.model';

/**
 * BedBoardComponent — Primary Angular component for the visual bed board floor plan.
 * Renders a responsive CSS Grid of colour-coded bed cells, integrates SignalR real-time updates,
 * and provides unit filtering with sessionStorage persistence.
 * Satisfies US-050 Scenario 1-4, accessible with WCAG 2.2 Level AA.
 *
 * @component
 * @example
 * <app-bed-board></app-bed-board>
 */
@Component({
  selector: 'app-bed-board',
  standalone: true,
  imports: [
    BedCellComponent,
    MatProgressSpinnerModule,
    MatButtonToggleModule,
  ],
  templateUrl: './bed-board.component.html',
  styleUrl: './bed-board.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  schemas: [CUSTOM_ELEMENTS_SCHEMA],
})
export class BedBoardComponent implements OnInit, OnDestroy {
  private readonly bedService = inject(BedBoardService);
  private readonly bedRealtime = inject(BedRealtimeService);

  // State signals
  readonly beds = signal<BedDto[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly selectedBed = signal<BedDto | null>(null);

  // Session storage key constant
  private static readonly UNIT_FILTER_KEY = 'bedboard_unit_filter';

  // Unit filter signals
  readonly selectedUnit = signal<string>(
    sessionStorage.getItem(BedBoardComponent.UNIT_FILTER_KEY) ?? 'ALL'
  );

  readonly availableUnits = computed(() =>
    ['ALL', ...new Set(this.beds().map(b => b.unit)).values()]
  );

  readonly filteredBeds = computed(() => {
    const unit = this.selectedUnit();
    return unit === 'ALL'
      ? this.beds()
      : this.beds().filter(b => b.unit === unit);
  });

  /**
   * Exposed for TASK-002 SignalR handler to update individual cells.
   * Patches the matching bed in the signal state without full refresh.
   */
  updateBedStatus(bedId: string, patch: Partial<BedDto>): void {
    this.beds.update(current =>
      current.map(b => (b.bedId === bedId ? { ...b, ...patch } : b))
    );
  }

  ngOnInit(): void {
    // Load initial bed data
    this.bedService.getBeds().subscribe({
      next: data => {
        this.beds.set(data);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        const errorMessage = this.getErrorMessage(err);
        this.error.set(errorMessage);
        this.loading.set(false);
      },
    });

    // Start SignalR subscription for real-time updates
    this.bedRealtime.start((event: BedUpdateEvent) => {
      this.updateBedStatus(event.bedId, {
        status: event.status,
        patientName: event.patientName,
        predictedDischargeTime: event.predictedDischargeTime,
      });
    });
  }

  /**
   * Maps HTTP errors to user-friendly messages.
   * Distinguishes between network timeouts, server errors, and generic failures.
   */
  private getErrorMessage(error: unknown): string {
    if (error instanceof Error) {
      if (error.message.includes('timeout')) {
        return 'Request timed out. Please check your connection and refresh.';
      }
      if (error.message.includes('404')) {
        return 'Bed data not found. Please contact support.';
      }
      if (error.message.includes('5')) {
        return 'Server error. Please try again later.';
      }
      if (error.message.includes('network')) {
        return 'Network connection failed. Please check your internet and refresh.';
      }
    }
    return 'Unable to load bed board. Please refresh.';
  }

  ngOnDestroy(): void {
    this.bedRealtime.stop();
  }

  onBedClick(bed: BedDto): void {
    this.selectedBed.set(bed);
  }

  onPanelClosed(): void {
    this.selectedBed.set(null);
  }

  onAssignBed(bed: BedDto): void {
    // Placeholder: assign bed functionality (US-051)
    console.log('Assign bed:', bed.bedId);
  }

  onUnitFilterChange(unit: string): void {
    this.selectedUnit.set(unit);
    sessionStorage.setItem(BedBoardComponent.UNIT_FILTER_KEY, unit);
  }
}
