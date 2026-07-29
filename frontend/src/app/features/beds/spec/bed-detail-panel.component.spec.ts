import { TestBed, ComponentFixture } from '@angular/core/testing';
import { BedDetailPanelComponent } from '../components/bed-detail-panel/bed-detail-panel.component';
import { BedDto } from '../models/bed.model';
import { AuthService } from '@core/auth/auth.service';
import { signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';

describe('BedDetailPanelComponent', () => {
  let component: BedDetailPanelComponent;
  let fixture: ComponentFixture<BedDetailPanelComponent>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  const mockBedOccupied: BedDto = {
    bedId: '3A-02',
    unit: '3A',
    status: 'OCCUPIED',
    patientName: 'John Doe',
    predictedDischargeTime: '2026-07-17T15:00:00Z',
    assignedNurse: 'N. Smith',
    riskTier: 'HIGH',
  };

  const mockBedVacant: BedDto = {
    bedId: '3A-01',
    unit: '3A',
    status: 'VACANT',
    patientName: null,
    predictedDischargeTime: null,
    assignedNurse: null,
    riskTier: null,
  };

  beforeEach(async () => {
    authServiceSpy = jasmine.createSpyObj('AuthService', [], {
      currentUser: signal({
        role: 'bed_manager',
        sub: 'test-user',
        email: 'test@example.com',
        units: ['3A'],
        iat: Date.now(),
        exp: Date.now() + 3600000,
      }),
    });

    await TestBed.configureTestingModule({
      imports: [BedDetailPanelComponent, MatButtonModule, MatChipsModule, MatIconModule],
      providers: [
        { provide: AuthService, useValue: authServiceSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(BedDetailPanelComponent);
    component = fixture.componentInstance;
  });

  it('should not open panel when bed is null', () => {
    component.bed = null;
    fixture.detectChanges();
    expect(component.isOpen).toBeFalse();
  });

  it('should open panel when bed is set', () => {
    component.bed = mockBedOccupied;
    fixture.detectChanges();
    expect(component.isOpen).toBeTrue();
  });

  it('should show full patient name for physician role', () => {
    (authServiceSpy.currentUser as any).mockReturnValue({
      role: 'physician',
      sub: 'test-user',
      email: 'test@example.com',
      units: ['3A'],
      iat: Date.now(),
      exp: Date.now() + 3600000,
    });
    component.bed = mockBedOccupied;
    fixture.detectChanges();
    expect(component.patientDisplayName).toBe('John Doe');
  });

  it('should show full patient name for charge_nurse role', () => {
    (authServiceSpy.currentUser as any).mockReturnValue({
      role: 'charge_nurse',
      sub: 'test-user',
      email: 'test@example.com',
      units: ['3A'],
      iat: Date.now(),
      exp: Date.now() + 3600000,
    });
    component.bed = mockBedOccupied;
    fixture.detectChanges();
    expect(component.patientDisplayName).toBe('John Doe');
  });

  it('should show masked initials for bed_manager role', () => {
    component.bed = mockBedOccupied;
    fixture.detectChanges();
    expect(component.patientDisplayName).toBe('J.D.');
  });

  it('should return correct risk chip class for HIGH risk', () => {
    component.bed = mockBedOccupied;
    expect(component.riskChipClass).toBe('risk-chip--high');
  });

  it('should return correct risk chip class for MEDIUM risk', () => {
    const mediumBed = { ...mockBedOccupied, riskTier: 'MEDIUM' as const };
    component.bed = mediumBed;
    expect(component.riskChipClass).toBe('risk-chip--medium');
  });

  it('should return correct risk chip class for LOW risk', () => {
    const lowBed = { ...mockBedOccupied, riskTier: 'LOW' as const };
    component.bed = lowBed;
    expect(component.riskChipClass).toBe('risk-chip--low');
  });

  it('should emit assignBed event when "Assign Bed" button clicked', () => {
    spyOn(component.assignBed, 'emit');
    component.bed = mockBedVacant;
    component.onAssignBed();
    expect(component.assignBed.emit).toHaveBeenCalledWith(mockBedVacant);
  });

  it('should close panel on Escape key', () => {
    spyOn(component.closed, 'emit');
    component.bed = mockBedOccupied;
    const event = new KeyboardEvent('keydown', { key: 'Escape' });
    component.onEscape();
    expect(component.closed.emit).toHaveBeenCalled();
  });
});
