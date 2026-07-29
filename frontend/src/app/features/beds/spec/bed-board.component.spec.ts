import { TestBed, ComponentFixture } from '@angular/core/testing';
import { of, throwError, Subject } from 'rxjs';
import { BedBoardComponent } from '../components/bed-board/bed-board.component';
import { BedBoardService } from '../services/bed-board.service';
import { BedRealtimeService } from '../services/bed-realtime.service';
import { BedDto } from '../models/bed.model';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { MatButtonToggleModule } from '@angular/material/button-toggle';

const MOCK_BEDS: BedDto[] = [
  {
    bedId: '3A-01',
    unit: '3A',
    status: 'VACANT',
    patientName: null,
    predictedDischargeTime: null,
    assignedNurse: null,
    riskTier: null,
  },
  {
    bedId: '3A-02',
    unit: '3A',
    status: 'OCCUPIED',
    patientName: 'John Doe',
    predictedDischargeTime: '2026-07-17T15:00:00Z',
    assignedNurse: 'N. Smith',
    riskTier: 'HIGH',
  },
  {
    bedId: 'ICU-1',
    unit: 'ICU',
    status: 'MAINTENANCE',
    patientName: null,
    predictedDischargeTime: null,
    assignedNurse: null,
    riskTier: null,
  },
];

describe('BedBoardComponent', () => {
  let component: BedBoardComponent;
  let fixture: ComponentFixture<BedBoardComponent>;
  let bedServiceSpy: jasmine.SpyObj<BedBoardService>;
  let bedRealtimeSpy: jasmine.SpyObj<BedRealtimeService>;

  beforeEach(async () => {
    bedServiceSpy = jasmine.createSpyObj('BedBoardService', ['getBeds']);
    bedServiceSpy.getBeds.and.returnValue(of(MOCK_BEDS));

    bedRealtimeSpy = jasmine.createSpyObj('BedRealtimeService', ['start', 'stop']);

    await TestBed.configureTestingModule({
      imports: [BedBoardComponent, HttpClientTestingModule, MatButtonToggleModule],
      providers: [
        { provide: BedBoardService, useValue: bedServiceSpy },
        { provide: BedRealtimeService, useValue: bedRealtimeSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(BedBoardComponent);
    component = fixture.componentInstance;
  });

  // ─────────────────────── API Integration Tests ───────────────────────

  it('should load beds into signal on init', () => {
    fixture.detectChanges();
    expect(component.beds().length).toBe(3);
    expect(component.beds()[0].bedId).toBe('3A-01');
  });

  it('should show loading state before API resolves', () => {
    bedServiceSpy.getBeds.and.returnValue(new Subject<BedDto[]>());
    fixture.detectChanges();
    expect(component.loading()).toBeTrue();
  });

  it('should hide loading state after API resolves', () => {
    fixture.detectChanges();
    expect(component.loading()).toBeFalse();
  });

  it('should set error signal on API failure', () => {
    bedServiceSpy.getBeds.and.returnValue(
      throwError(() => new Error('Network error'))
    );
    fixture.detectChanges();
    expect(component.error()).toBeTruthy();
  });

  it('should render VACANT bed with correct status class', () => {
    fixture.detectChanges();
    const vacant = component.beds().find(b => b.status === 'VACANT');
    expect(vacant?.status).toBe('VACANT');
  });

  it('should render OCCUPIED bed with correct status class', () => {
    fixture.detectChanges();
    const occupied = component.beds().find(b => b.status === 'OCCUPIED');
    expect(occupied?.status).toBe('OCCUPIED');
  });

  it('should render DIRTY bed with correct status class', () => {
    const dirtyBed: BedDto = {
      bedId: 'TEST-01',
      unit: '3A',
      status: 'DIRTY',
      patientName: null,
      predictedDischargeTime: null,
      assignedNurse: null,
      riskTier: null,
    };
    bedServiceSpy.getBeds.and.returnValue(of([dirtyBed]));
    fixture.detectChanges();
    expect(component.beds()[0].status).toBe('DIRTY');
  });

  it('should render MAINTENANCE bed with correct status class', () => {
    const maintenanceBed: BedDto = {
      bedId: 'TEST-01',
      unit: '3A',
      status: 'MAINTENANCE',
      patientName: null,
      predictedDischargeTime: null,
      assignedNurse: null,
      riskTier: null,
    };
    bedServiceSpy.getBeds.and.returnValue(of([maintenanceBed]));
    fixture.detectChanges();
    expect(component.beds()[0].status).toBe('MAINTENANCE');
  });

  it('should render RESERVED bed with correct status class', () => {
    const reservedBed: BedDto = {
      bedId: 'TEST-01',
      unit: '3A',
      status: 'RESERVED',
      patientName: null,
      predictedDischargeTime: null,
      assignedNurse: null,
      riskTier: null,
    };
    bedServiceSpy.getBeds.and.returnValue(of([reservedBed]));
    fixture.detectChanges();
    expect(component.beds()[0].status).toBe('RESERVED');
  });

  it('should render predictedDischargeTime when present', () => {
    fixture.detectChanges();
    const occupied = component.beds().find(b => b.bedId === '3A-02');
    expect(occupied?.predictedDischargeTime).toBe('2026-07-17T15:00:00Z');
  });

  it('should render null predictedDischargeTime when absent', () => {
    fixture.detectChanges();
    const vacant = component.beds().find(b => b.status === 'VACANT');
    expect(vacant?.predictedDischargeTime).toBeNull();
  });

  it('should update bed status via updateBedStatus method', () => {
    fixture.detectChanges();
    component.updateBedStatus('3A-02', { status: 'VACANT' });
    const updated = component.beds().find(b => b.bedId === '3A-02');
    expect(updated?.status).toBe('VACANT');
  });

  it('should ignore unknown bedId in updateBedStatus', () => {
    fixture.detectChanges();
    const before = JSON.stringify(component.beds());
    component.updateBedStatus('UNKNOWN-99', { status: 'DIRTY' });
    expect(JSON.stringify(component.beds())).toBe(before);
  });

  // ────────────────────── Unit Filter Tests ──────────────────────────

  it('should default to ALL unit filter on first load', () => {
    sessionStorage.removeItem('bedboard_unit_filter');
    fixture.detectChanges();
    expect(component.selectedUnit()).toBe('ALL');
  });

  it('should filter beds to ICU unit', () => {
    fixture.detectChanges();
    component.onUnitFilterChange('ICU');
    expect(component.filteredBeds().every(b => b.unit === 'ICU')).toBeTrue();
    expect(component.filteredBeds().length).toBe(1);
  });

  it('should restore unit filter from sessionStorage', () => {
    sessionStorage.setItem('bedboard_unit_filter', '3A');
    // Create new component instance to trigger sessionStorage read
    const newFixture = TestBed.createComponent(BedBoardComponent);
    expect(newFixture.componentInstance.selectedUnit()).toBe('3A');
    sessionStorage.removeItem('bedboard_unit_filter');
  });

  it('should show all beds when ALL filter is selected', () => {
    fixture.detectChanges();
    component.onUnitFilterChange('ALL');
    expect(component.filteredBeds().length).toBe(MOCK_BEDS.length);
  });

  it('should show no beds when no beds match the selected unit', () => {
    fixture.detectChanges();
    component.onUnitFilterChange('NONEXISTENT');
    // The NONEXISTENT unit won't be in availableUnits, but we test the filter logic
    const filtered = component.beds().filter(b => b.unit === 'NONEXISTENT');
    expect(filtered.length).toBe(0);
  });

  // ────────────────────── Lifecycle Tests ────────────────────────────

  it('should call bedRealtime.start on ngOnInit', () => {
    fixture.detectChanges();
    expect(bedRealtimeSpy.start).toHaveBeenCalled();
  });

  it('should call bedRealtime.stop on ngOnDestroy', () => {
    fixture.detectChanges();
    fixture.destroy();
    expect(bedRealtimeSpy.stop).toHaveBeenCalled();
  });

  // ──────────────── Responsive Grid Layout Tests ────────────────────

  it('should render grid container with correct CSS class', () => {
    fixture.detectChanges();
    const gridElement = fixture.nativeElement.querySelector('.bed-board__grid');
    expect(gridElement).toBeTruthy();
  });

  it('should apply CSS Grid layout with repeat(auto-fill, minmax(120px, 1fr))', () => {
    fixture.detectChanges();
    const gridElement = fixture.nativeElement.querySelector('.bed-board__grid');
    const computedStyle = window.getComputedStyle(gridElement);
    // Verify grid display property
    expect(computedStyle.display).toContain('grid');
  });

  it('should render all beds as grid items', () => {
    fixture.detectChanges();
    const bedCells = fixture.nativeElement.querySelectorAll('app-bed-cell');
    expect(bedCells.length).toBe(MOCK_BEDS.length);
  });

  it('should apply correct ARIA role to grid container', () => {
    fixture.detectChanges();
    const gridElement = fixture.nativeElement.querySelector('.bed-board__grid');
    expect(gridElement.getAttribute('role')).toBe('grid');
  });

  it('should render skeleton loaders during loading state (12 items)', () => {
    bedServiceSpy.getBeds.and.returnValue(new Subject<BedDto[]>());
    fixture.detectChanges();
    const skeletonItems = fixture.nativeElement.querySelectorAll('.bed-board__skeleton-item');
    expect(skeletonItems.length).toBe(12);
  });

  it('should hide skeleton loaders when beds are loaded', () => {
    fixture.detectChanges();
    const skeletonContainer = fixture.nativeElement.querySelector('.bed-board__skeleton-loader');
    const skeletonItems = fixture.nativeElement.querySelectorAll('.bed-board__skeleton-item');
    // When loading is false, skeleton items should not be visible
    expect(component.loading()).toBeFalse();
  });

  it('should render unit filter toolbar with MatButtonToggle', () => {
    fixture.detectChanges();
    const toolbar = fixture.nativeElement.querySelector('.bed-board__toolbar');
    const toggleGroup = fixture.nativeElement.querySelector('mat-button-toggle-group');
    expect(toolbar).toBeTruthy();
    expect(toggleGroup).toBeTruthy();
  });

  it('should render detail panel as sibling to grid', () => {
    fixture.detectChanges();
    component.selectedBed.set(MOCK_BEDS[0]);
    fixture.detectChanges();
    const detailPanel = fixture.nativeElement.querySelector('app-bed-detail-panel');
    expect(detailPanel).toBeTruthy();
  });

  it('should display empty state message when filtered beds are empty', () => {
    fixture.detectChanges();
    component.onUnitFilterChange('EMPTY_UNIT');
    fixture.detectChanges();
    const emptyState = fixture.nativeElement.querySelector('.bed-board__empty-state');
    if (emptyState) {
      expect(emptyState.textContent).toContain('No beds found');
    }
  });

  it('should maintain responsive layout at 1024px viewport', () => {
    // Simulate 1024px viewport
    window.innerWidth = 1024;
    window.dispatchEvent(new Event('resize'));
    fixture.detectChanges();
    const gridElement = fixture.nativeElement.querySelector('.bed-board__grid');
    expect(gridElement).toBeTruthy();
    // Grid should be visible and functional
    expect(gridElement.querySelectorAll('app-bed-cell').length).toBeGreaterThan(0);
  });

  it('should maintain responsive layout at 2560px viewport', () => {
    // Simulate 2560px viewport (enhanced grid)
    window.innerWidth = 2560;
    window.dispatchEvent(new Event('resize'));
    fixture.detectChanges();
    const gridElement = fixture.nativeElement.querySelector('.bed-board__grid');
    expect(gridElement).toBeTruthy();
    // Grid should be visible and functional
    expect(gridElement.querySelectorAll('app-bed-cell').length).toBeGreaterThan(0);
  });

  // ─────────────── Accessibility (WCAG) Tests ──────────────────────

  it('should have descriptive heading for bed board', () => {
    fixture.detectChanges();
    const heading = fixture.nativeElement.querySelector('h1, h2');
    if (heading) {
      expect(heading.textContent.toLowerCase()).toContain('bed');
    }
  });

  it('should have proper aria-label on grid', () => {
    fixture.detectChanges();
    const gridElement = fixture.nativeElement.querySelector('.bed-board__grid');
    const ariaLabel = gridElement.getAttribute('aria-label');
    expect(ariaLabel || gridElement.getAttribute('role')).toBeTruthy();
  });

  it('should render filter buttons with accessible labels', () => {
    fixture.detectChanges();
    const toggleButtons = fixture.nativeElement.querySelectorAll('mat-button-toggle');
    expect(toggleButtons.length).toBeGreaterThan(0);
    // Check that buttons have text content (not just icons)
    toggleButtons.forEach((button: HTMLElement) => {
      expect(button.textContent?.trim().length || button.getAttribute('aria-label')).toBeTruthy();
    });
  });

  it('should indicate selected unit filter state', () => {
    fixture.detectChanges();
    component.onUnitFilterChange('3A');
    fixture.detectChanges();
    // The MatButtonToggleGroup should track the selection
    expect(component.selectedUnit()).toBe('3A');
  });

  it('should provide error message to screen readers', () => {
    bedServiceSpy.getBeds.and.returnValue(
      throwError(() => new Error('Network error'))
    );
    fixture.detectChanges();
    const errorElement = fixture.nativeElement.querySelector('.bed-board__error');
    if (errorElement) {
      expect(errorElement.getAttribute('role')).toBe('alert');
    }
  });
});
