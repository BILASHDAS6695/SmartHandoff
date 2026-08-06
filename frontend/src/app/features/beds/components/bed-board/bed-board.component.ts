import { Component, OnInit, signal, inject, ChangeDetectionStrategy, OnDestroy, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { BedDetailPanelComponent } from '../bed-detail-panel/bed-detail-panel.component';
import { BedDto, BedStatus } from '../../models/bed.model';

interface EdAlert {
  patientName: string;
  waitingSince: string;
  waitingTime: string;
  acuity: string;
  recommendedBeds: { bedId: string; bestMatch: boolean }[];
}

interface DischargePrediction {
  patientName: string;
  bedId: string;
  time: string;
}

/**
 * BedBoardComponent — Visual bed board floor plan matching Hi-Fi wireframe.
 */
@Component({
  selector: 'app-bed-board',
  standalone: true,
  imports: [
    CommonModule,
    BedDetailPanelComponent,
    MatProgressSpinnerModule,
    MatButtonToggleModule,
    MatSelectModule,
    MatIconModule,
  ],
  templateUrl: './bed-board.component.html',
  styleUrl: './bed-board.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedBoardComponent implements OnInit, OnDestroy {
  // State signals
  readonly beds = signal<BedDto[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly selectedBed = signal<BedDto | null>(null);
  readonly lastUpdated = signal<string>('14:39:01');

  readonly selectedUnit = signal<string>('All Units');
  readonly selectedStatus = signal<string>('All Status');

  readonly availableUnits = signal<string[]>(['All Units', '4-West', '3-North', 'ICU']);
  readonly availableStatuses = signal<string[]>(['All Status', 'Clean', 'Dirty', 'Occupied', 'Blocked']);

  readonly edAlert = signal<EdAlert | null>({
    patientName: 'Garcia, Maria',
    waitingSince: '12:24',
    waitingTime: '2h 15m',
    acuity: 'High',
    recommendedBeds: [
      { bedId: '4W-03', bestMatch: true },
      { bedId: '3N-07', bestMatch: false },
      { bedId: '3N-12', bestMatch: false },
    ],
  });

  readonly dischargePredictions = signal<DischargePrediction[]>([
    { patientName: 'Jones, M.', bedId: '4W-05', time: '~16:00' },
    { patientName: 'Patel, R.', bedId: '4W-04', time: '~18:30' },
    { patientName: 'Lee, K.', bedId: '3N-04', time: '~17:15' },
    { patientName: 'Nguyen, L.', bedId: '4W-07', time: '~14:00 tomorrow' },
  ]);

  readonly filteredBeds = computed(() => {
    let result = this.beds();
    const unit = this.selectedUnit();
    const status = this.selectedStatus();

    if (unit !== 'All Units') {
      result = result.filter(b => b.unit === unit);
    }

    if (status !== 'All Status') {
      result = result.filter(b => this.mapStatusLabel(b.status) === status);
    }

    return result;
  });

  // Static mock data
  private readonly mockBeds: BedDto[] = [
    { bedId: '4W-01', unit: '4-West', status: 'OCCUPIED', patientName: 'Smith, J.', predictedDischargeTime: '16h', assignedNurse: null, riskTier: 'HIGH' },
    { bedId: '4W-02', unit: '4-West', status: 'DIRTY', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
    { bedId: '4W-03', unit: '4-West', status: 'VACANT', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
    { bedId: '4W-04', unit: '4-West', status: 'OCCUPIED', patientName: 'Patel, R.', predictedDischargeTime: '32h', assignedNurse: null, riskTier: 'MEDIUM' },
    { bedId: '4W-05', unit: '4-West', status: 'OCCUPIED', patientName: 'Jones, M.', predictedDischargeTime: '8h', assignedNurse: null, riskTier: 'LOW' },
    { bedId: '4W-06', unit: '4-West', status: 'MAINTENANCE', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
    { bedId: '4W-07', unit: '4-West', status: 'OCCUPIED', patientName: 'Nguyen, L.', predictedDischargeTime: '24h', assignedNurse: null, riskTier: 'LOW' },
    { bedId: '4W-08', unit: '4-West', status: 'VACANT', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
  ];

  ngOnInit(): void {
    // Simulate loading static data
    setTimeout(() => {
      this.beds.set(this.mockBeds);
      this.loading.set(false);
    }, 500);
  }

  ngOnDestroy(): void {
    // No SignalR in static preview
  }

  onUnitFilterChange(unit: string): void {
    this.selectedUnit.set(unit);
  }

  onStatusFilterChange(status: string): void {
    this.selectedStatus.set(status);
  }

  onBedClick(bed: BedDto): void {
    this.selectedBed.set(bed);
  }

  onPanelClosed(): void {
    this.selectedBed.set(null);
  }

  refresh(): void {
    this.loading.set(true);
    setTimeout(() => {
      this.lastUpdated.set(new Date().toLocaleTimeString('en-US', { hour12: false }));
      this.loading.set(false);
    }, 500);
  }

  mapStatusLabel(status: BedStatus): string {
    switch (status) {
      case 'VACANT': return 'Clean';
      case 'OCCUPIED': return 'Occupied';
      case 'DIRTY': return 'Dirty';
      case 'MAINTENANCE': return 'Blocked';
      case 'RESERVED': return 'Blocked';
      default: return status;
    }
  }

  getBedClass(status: BedStatus): string {
    switch (status) {
      case 'VACANT': return 'clean';
      case 'OCCUPIED': return 'occupied';
      case 'DIRTY': return 'dirty';
      case 'MAINTENANCE': return 'blocked';
      case 'RESERVED': return 'blocked';
      default: return 'blocked';
    }
  }

  getRiskClass(tier: string | null): string {
    switch (tier) {
      case 'HIGH': return 'high';
      case 'MEDIUM': return 'med';
      case 'LOW': return 'low';
      default: return '';
    }
  }

  getRiskLabel(tier: string | null): string {
    switch (tier) {
      case 'HIGH': return '0.82 HIGH';
      case 'MEDIUM': return '0.45 MED';
      case 'LOW': return '0.20 LOW';
      default: return '';
    }
  }

  assignBed(bedId: string): void {
    this.edAlert.set(null);
  }

  dismissAlert(): void {
    this.edAlert.set(null);
  }
}
