/**
 * Unit tests for BedStatusHandlerService
 * US-048 TASK-002
 */
import { TestBed } from '@angular/core/testing';
import { BedStatusHandlerService } from './bed-status-handler.service';
import { BedStatusPayload, BedStatus } from '@core/signalr/signalr.models';

describe('BedStatusHandlerService', () => {
  let service: BedStatusHandlerService;

  const createMockBedStatus = (index: number, status: BedStatus = 'AVAILABLE'): BedStatusPayload => ({
    bedId: `BED-${String(index).padStart(3, '0')}`,
    patientUnit: `${(index % 5) + 1}A`,
    status,
    occupancyDuration: status === 'OCCUPIED' ? 3600000 : null,
    lastUpdated: new Date().toISOString(),
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [BedStatusHandlerService],
    });
    service = TestBed.inject(BedStatusHandlerService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('Initialization', () => {
    it('should initialize with empty bed status map', () => {
      expect(service.bedStatusMap()).toEqual({});
    });

    it('should initialize available beds count to zero', () => {
      expect(service.availableBedCount()).toBe(0);
    });

    it('should initialize occupied beds count to zero', () => {
      expect(service.occupiedBedCount()).toBe(0);
    });

    it('should initialize total beds count to zero', () => {
      expect(service.totalBedCount()).toBe(0);
    });
  });

  describe('Handling bed status updates', () => {
    it('should add new bed status to map', () => {
      const bedStatus = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bedStatus);

      const map = service.bedStatusMap();
      expect(map['BED-001']).toEqual(bedStatus);
    });

    it('should update existing bed status', () => {
      const bedStatus1 = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bedStatus1);

      const bedStatus2 = { ...bedStatus1, status: 'OCCUPIED' as BedStatus };
      service.handleBedStatus(bedStatus2);

      const map = service.bedStatusMap();
      expect(map['BED-001'].status).toBe('OCCUPIED');
    });

    it('should handle multiple bed updates', () => {
      const beds = [
        createMockBedStatus(1, 'AVAILABLE'),
        createMockBedStatus(2, 'OCCUPIED'),
        createMockBedStatus(3, 'AVAILABLE'),
      ];

      beds.forEach((bed) => service.handleBedStatus(bed));

      const map = service.bedStatusMap();
      expect(Object.keys(map).length).toBe(3);
    });
  });

  describe('Bed status counts', () => {
    beforeEach(() => {
      const beds = [
        createMockBedStatus(1, 'AVAILABLE'),
        createMockBedStatus(2, 'OCCUPIED'),
        createMockBedStatus(3, 'AVAILABLE'),
        createMockBedStatus(4, 'OCCUPIED'),
        createMockBedStatus(5, 'MAINTENANCE'),
      ];
      beds.forEach((bed) => service.handleBedStatus(bed));
    });

    it('should calculate available bed count correctly', () => {
      expect(service.availableBedCount()).toBe(2);
    });

    it('should calculate occupied bed count correctly', () => {
      expect(service.occupiedBedCount()).toBe(2);
    });

    it('should calculate total bed count correctly', () => {
      expect(service.totalBedCount()).toBe(5);
    });

    it('should update counts when bed status changes', () => {
      const bed = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bed);
      expect(service.availableBedCount()).toBe(2);

      const updatedBed = { ...bed, status: 'OCCUPIED' as BedStatus };
      service.handleBedStatus(updatedBed);
      expect(service.availableBedCount()).toBe(1);
      expect(service.occupiedBedCount()).toBe(3);
    });
  });

  describe('Filtering beds by status', () => {
    beforeEach(() => {
      const beds = [
        createMockBedStatus(1, 'AVAILABLE'),
        createMockBedStatus(2, 'OCCUPIED'),
        createMockBedStatus(3, 'AVAILABLE'),
        createMockBedStatus(4, 'OCCUPIED'),
        createMockBedStatus(5, 'MAINTENANCE'),
      ];
      beds.forEach((bed) => service.handleBedStatus(bed));
    });

    it('should return all available beds', () => {
      const availableBeds = service.getBedsByStatus('AVAILABLE');
      expect(availableBeds.length).toBe(2);
      availableBeds.forEach((bed) => expect(bed.status).toBe('AVAILABLE'));
    });

    it('should return all occupied beds', () => {
      const occupiedBeds = service.getBedsByStatus('OCCUPIED');
      expect(occupiedBeds.length).toBe(2);
      occupiedBeds.forEach((bed) => expect(bed.status).toBe('OCCUPIED'));
    });

    it('should return maintenance beds', () => {
      const maintenanceBeds = service.getBedsByStatus('MAINTENANCE');
      expect(maintenanceBeds.length).toBe(1);
      maintenanceBeds.forEach((bed) => expect(bed.status).toBe('MAINTENANCE'));
    });

    it('should return empty array for status with no beds', () => {
      service.bedStatusMap.set({});
      const beds = service.getBedsByStatus('AVAILABLE');
      expect(beds.length).toBe(0);
    });
  });

  describe('Filtering beds by unit', () => {
    beforeEach(() => {
      const beds = [
        createMockBedStatus(1, 'AVAILABLE'),
        createMockBedStatus(6, 'OCCUPIED'),
        createMockBedStatus(11, 'AVAILABLE'),
      ];
      beds.forEach((bed) => service.handleBedStatus(bed));
    });

    it('should return beds in specific unit', () => {
      const bedsInUnit = service.getBedsByUnit('1A');
      expect(bedsInUnit.length).toBeGreaterThan(0);
      bedsInUnit.forEach((bed) => expect(bed.patientUnit).toBe('1A'));
    });

    it('should return empty array for unit with no beds', () => {
      const bedsInUnit = service.getBedsByUnit('10A');
      expect(bedsInUnit.length).toBe(0);
    });
  });

  describe('Getting single bed status', () => {
    beforeEach(() => {
      const beds = [
        createMockBedStatus(1, 'AVAILABLE'),
        createMockBedStatus(2, 'OCCUPIED'),
      ];
      beds.forEach((bed) => service.handleBedStatus(bed));
    });

    it('should return bed status for valid bed ID', () => {
      const bed = service.getBedStatus('BED-001');
      expect(bed).toBeTruthy();
      expect(bed?.bedId).toBe('BED-001');
    });

    it('should return null for non-existent bed ID', () => {
      const bed = service.getBedStatus('BED-999');
      expect(bed).toBeNull();
    });
  });

  describe('Occupancy duration tracking', () => {
    it('should preserve occupancy duration for occupied beds', () => {
      const bedStatus = {
        ...createMockBedStatus(1, 'OCCUPIED'),
        occupancyDuration: 7200000,
      };
      service.handleBedStatus(bedStatus);

      const stored = service.getBedStatus('BED-001');
      expect(stored?.occupancyDuration).toBe(7200000);
    });

    it('should have null occupancy duration for available beds', () => {
      const bedStatus = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bedStatus);

      const stored = service.getBedStatus('BED-001');
      expect(stored?.occupancyDuration).toBeNull();
    });
  });

  describe('Last updated tracking', () => {
    it('should preserve last updated timestamp', () => {
      const now = new Date().toISOString();
      const bedStatus = {
        ...createMockBedStatus(1),
        lastUpdated: now,
      };
      service.handleBedStatus(bedStatus);

      const stored = service.getBedStatus('BED-001');
      expect(stored?.lastUpdated).toBe(now);
    });

    it('should update lastUpdated when bed status changes', () => {
      const bed1 = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bed1);

      const bed2 = { ...bed1, lastUpdated: new Date().toISOString() };
      service.handleBedStatus(bed2);

      const stored = service.getBedStatus('BED-001');
      expect(stored?.lastUpdated).toBe(bed2.lastUpdated);
    });
  });

  describe('Clearing bed statuses', () => {
    beforeEach(() => {
      const beds = [
        createMockBedStatus(1, 'AVAILABLE'),
        createMockBedStatus(2, 'OCCUPIED'),
        createMockBedStatus(3, 'AVAILABLE'),
      ];
      beds.forEach((bed) => service.handleBedStatus(bed));
    });

    it('should clear all bed statuses', () => {
      expect(service.totalBedCount()).toBe(3);

      service.clearAllBeds();

      expect(service.bedStatusMap()).toEqual({});
      expect(service.totalBedCount()).toBe(0);
    });

    it('should clear beds by unit', () => {
      const unitBedCount = service.getBedsByUnit('1A').length;
      service.clearBedsByUnit('1A');

      const remaining = service.getBedsByUnit('1A');
      expect(remaining.length).toBeLessThan(unitBedCount);
    });

    it('should update counts after clearing', () => {
      expect(service.totalBedCount()).toBe(3);
      service.clearAllBeds();
      expect(service.totalBedCount()).toBe(0);
      expect(service.availableBedCount()).toBe(0);
      expect(service.occupiedBedCount()).toBe(0);
    });
  });

  describe('Computed signals reactivity', () => {
    it('should update available count reactively', () => {
      expect(service.availableBedCount()).toBe(0);

      service.handleBedStatus(createMockBedStatus(1, 'AVAILABLE'));
      expect(service.availableBedCount()).toBe(1);

      service.handleBedStatus(createMockBedStatus(2, 'AVAILABLE'));
      expect(service.availableBedCount()).toBe(2);
    });

    it('should update occupied count reactively', () => {
      expect(service.occupiedBedCount()).toBe(0);

      service.handleBedStatus(createMockBedStatus(1, 'OCCUPIED'));
      expect(service.occupiedBedCount()).toBe(1);

      service.handleBedStatus(createMockBedStatus(2, 'OCCUPIED'));
      expect(service.occupiedBedCount()).toBe(2);
    });

    it('should update total count reactively', () => {
      expect(service.totalBedCount()).toBe(0);

      service.handleBedStatus(createMockBedStatus(1, 'AVAILABLE'));
      expect(service.totalBedCount()).toBe(1);

      service.handleBedStatus(createMockBedStatus(2, 'OCCUPIED'));
      expect(service.totalBedCount()).toBe(2);
    });
  });

  describe('Bed status transitions', () => {
    it('should handle transition from AVAILABLE to OCCUPIED', () => {
      const bed = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bed);
      expect(service.availableBedCount()).toBe(1);
      expect(service.occupiedBedCount()).toBe(0);

      const updated = { ...bed, status: 'OCCUPIED' as BedStatus };
      service.handleBedStatus(updated);
      expect(service.availableBedCount()).toBe(0);
      expect(service.occupiedBedCount()).toBe(1);
    });

    it('should handle transition from OCCUPIED to MAINTENANCE', () => {
      const bed = createMockBedStatus(1, 'OCCUPIED');
      service.handleBedStatus(bed);
      expect(service.occupiedBedCount()).toBe(1);

      const updated = { ...bed, status: 'MAINTENANCE' as BedStatus };
      service.handleBedStatus(updated);
      expect(service.occupiedBedCount()).toBe(0);
    });

    it('should handle transition to AVAILABLE after maintenance', () => {
      const bed = createMockBedStatus(1, 'MAINTENANCE');
      service.handleBedStatus(bed);
      expect(service.availableBedCount()).toBe(0);

      const updated = { ...bed, status: 'AVAILABLE' as BedStatus };
      service.handleBedStatus(updated);
      expect(service.availableBedCount()).toBe(1);
    });
  });

  describe('Error handling', () => {
    it('should handle null bed status gracefully', () => {
      expect(() => {
        service.handleBedStatus(null as any);
      }).not.toThrow();
    });

    it('should handle undefined bed status gracefully', () => {
      expect(() => {
        service.handleBedStatus(undefined as any);
      }).not.toThrow();
    });

    it('should return null for null bed ID lookup', () => {
      const bed = service.getBedStatus(null as any);
      expect(bed).toBeNull();
    });
  });

  describe('Service lifecycle', () => {
    it('should maintain state across method calls', () => {
      service.handleBedStatus(createMockBedStatus(1, 'AVAILABLE'));
      expect(service.totalBedCount()).toBe(1);

      service.handleBedStatus(createMockBedStatus(2, 'OCCUPIED'));
      expect(service.totalBedCount()).toBe(2);

      const bed = service.getBedStatus('BED-001');
      expect(bed).toBeTruthy();
    });

    it('should provide consistent data across multiple calls', () => {
      const bed = createMockBedStatus(1, 'AVAILABLE');
      service.handleBedStatus(bed);

      const retrieved1 = service.getBedStatus('BED-001');
      const retrieved2 = service.getBedStatus('BED-001');

      expect(retrieved1).toEqual(retrieved2);
    });
  });
});
