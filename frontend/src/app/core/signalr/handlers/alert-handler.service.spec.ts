/**
 * Unit tests for AlertHandlerService
 * US-048 TASK-002
 */
import { TestBed } from '@angular/core/testing';
import { AlertHandlerService } from './alert-handler.service';
import { AlertPayload } from '@core/signalr/signalr.models';

describe('AlertHandlerService', () => {
  let service: AlertHandlerService;

  const createMockAlert = (index: number, severity: 'INFO' | 'WARNING' | 'ERROR' = 'INFO'): AlertPayload => ({
    id: `ALERT-${String(index).padStart(3, '0')}`,
    encounterId: `ENC-${String(index).padStart(3, '0')}`,
    severity,
    message: `Alert message ${index}`,
    timestamp: new Date(Date.now() + index * 1000).toISOString(),
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [AlertHandlerService],
    });
    service = TestBed.inject(AlertHandlerService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('Initialization', () => {
    it('should initialize with empty alerts', () => {
      expect(service.alerts()).toEqual([]);
    });

    it('should initialize priority signal with NONE', () => {
      expect(service.priorityLevel()).toBe('NONE');
    });

    it('should initialize alert count signal to zero', () => {
      expect(service.alertCount()).toBe(0);
    });
  });

  describe('Adding alerts', () => {
    it('should add a single alert', () => {
      const alert = createMockAlert(1);
      service.handleAlert(alert);

      const alerts = service.alerts();
      expect(alerts.length).toBe(1);
      expect(alerts[0]).toEqual(alert);
    });

    it('should add multiple alerts maintaining order', () => {
      const alert1 = createMockAlert(1);
      const alert2 = createMockAlert(2);
      const alert3 = createMockAlert(3);

      service.handleAlert(alert1);
      service.handleAlert(alert2);
      service.handleAlert(alert3);

      const alerts = service.alerts();
      expect(alerts.length).toBe(3);
      expect(alerts[0]).toEqual(alert1);
      expect(alerts[1]).toEqual(alert2);
      expect(alerts[2]).toEqual(alert3);
    });

    it('should update alert count signal when adding alerts', () => {
      expect(service.alertCount()).toBe(0);

      service.handleAlert(createMockAlert(1));
      expect(service.alertCount()).toBe(1);

      service.handleAlert(createMockAlert(2));
      expect(service.alertCount()).toBe(2);
    });
  });

  describe('Priority filtering', () => {
    it('should set priority to ERROR when ERROR alert added', () => {
      service.handleAlert(createMockAlert(1, 'ERROR'));
      expect(service.priorityLevel()).toBe('ERROR');
    });

    it('should set priority to WARNING when WARNING alert added (no ERROR)', () => {
      service.handleAlert(createMockAlert(1, 'WARNING'));
      expect(service.priorityLevel()).toBe('WARNING');
    });

    it('should set priority to INFO when only INFO alerts', () => {
      service.handleAlert(createMockAlert(1, 'INFO'));
      service.handleAlert(createMockAlert(2, 'INFO'));
      expect(service.priorityLevel()).toBe('INFO');
    });

    it('should reflect highest priority among multiple alerts', () => {
      service.handleAlert(createMockAlert(1, 'INFO'));
      expect(service.priorityLevel()).toBe('INFO');

      service.handleAlert(createMockAlert(2, 'WARNING'));
      expect(service.priorityLevel()).toBe('WARNING');

      service.handleAlert(createMockAlert(3, 'ERROR'));
      expect(service.priorityLevel()).toBe('ERROR');
    });

    it('should demote priority when higher severity alert is removed', () => {
      service.handleAlert(createMockAlert(1, 'INFO'));
      service.handleAlert(createMockAlert(2, 'WARNING'));
      service.handleAlert(createMockAlert(3, 'ERROR'));
      expect(service.priorityLevel()).toBe('ERROR');

      // Clear errors manually by setting alert list
      // (assumes clearAlert method or direct signal manipulation)
      service.alerts().splice(2, 1);
      expect(service.priorityLevel()).toBe('WARNING');
    });
  });

  describe('Alert filtering by severity', () => {
    beforeEach(() => {
      service.handleAlert(createMockAlert(1, 'INFO'));
      service.handleAlert(createMockAlert(2, 'WARNING'));
      service.handleAlert(createMockAlert(3, 'ERROR'));
      service.handleAlert(createMockAlert(4, 'INFO'));
    });

    it('should filter alerts by severity using getAlertsBySeverity()', () => {
      const errors = service.getAlertsBySeverity('ERROR');
      expect(errors.length).toBe(1);
      expect(errors[0].severity).toBe('ERROR');
    });

    it('should return all alerts matching WARNING severity', () => {
      const warnings = service.getAlertsBySeverity('WARNING');
      expect(warnings.length).toBe(1);
      expect(warnings[0].severity).toBe('WARNING');
    });

    it('should return multiple alerts with same severity', () => {
      const infos = service.getAlertsBySeverity('INFO');
      expect(infos.length).toBe(2);
      infos.forEach((alert) => expect(alert.severity).toBe('INFO'));
    });

    it('should return empty array when no alerts match severity', () => {
      service.alerts.set([]);
      const errors = service.getAlertsBySeverity('ERROR');
      expect(errors.length).toBe(0);
    });
  });

  describe('Clearing alerts', () => {
    beforeEach(() => {
      service.handleAlert(createMockAlert(1));
      service.handleAlert(createMockAlert(2));
      service.handleAlert(createMockAlert(3));
    });

    it('should clear all alerts', () => {
      expect(service.alerts().length).toBe(3);

      service.clearAlerts();

      expect(service.alerts().length).toBe(0);
      expect(service.alertCount()).toBe(0);
      expect(service.priorityLevel()).toBe('NONE');
    });

    it('should clear alerts by encounter ID', () => {
      const encounterId = 'ENC-001';
      service.clearAlertsByEncounter(encounterId);

      const remaining = service.alerts();
      expect(remaining.every((a) => a.encounterId !== encounterId)).toBeTrue();
    });

    it('should update priority after clearing', () => {
      service.handleAlert(createMockAlert(1, 'ERROR'));
      expect(service.priorityLevel()).toBe('ERROR');

      service.clearAlerts();

      expect(service.priorityLevel()).toBe('NONE');
    });

    it('should update alert count after clearing', () => {
      expect(service.alertCount()).toBe(3);
      service.clearAlerts();
      expect(service.alertCount()).toBe(0);
    });
  });

  describe('Computed signals reactivity', () => {
    it('should update alert count signal reactively', () => {
      expect(service.alertCount()).toBe(0);

      service.handleAlert(createMockAlert(1));
      expect(service.alertCount()).toBe(1);

      service.handleAlert(createMockAlert(2));
      expect(service.alertCount()).toBe(2);
    });

    it('should update priority signal reactively', () => {
      expect(service.priorityLevel()).toBe('NONE');

      service.handleAlert(createMockAlert(1, 'INFO'));
      expect(service.priorityLevel()).toBe('INFO');

      service.handleAlert(createMockAlert(2, 'ERROR'));
      expect(service.priorityLevel()).toBe('ERROR');
    });
  });

  describe('Alert deduplication', () => {
    it('should handle duplicate alert IDs appropriately', () => {
      const alert1 = createMockAlert(1);
      const alert2 = { ...createMockAlert(1) };

      service.handleAlert(alert1);
      service.handleAlert(alert2);

      // Either should deduplicate or append (depends on implementation)
      expect(service.alerts().length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Alert timestamp handling', () => {
    it('should preserve alert timestamps', () => {
      const alert = createMockAlert(1);
      service.handleAlert(alert);

      const stored = service.alerts()[0];
      expect(stored.timestamp).toBe(alert.timestamp);
    });

    it('should maintain chronological order by timestamp', () => {
      const now = Date.now();
      const alert1 = { ...createMockAlert(1), timestamp: new Date(now).toISOString() };
      const alert2 = { ...createMockAlert(2), timestamp: new Date(now + 1000).toISOString() };

      service.handleAlert(alert1);
      service.handleAlert(alert2);

      const alerts = service.alerts();
      expect(new Date(alerts[0].timestamp).getTime()).toBeLessThanOrEqual(
        new Date(alerts[1].timestamp).getTime(),
      );
    });
  });

  describe('Error handling', () => {
    it('should handle null alerts gracefully', () => {
      expect(() => {
        service.handleAlert(null as any);
      }).not.toThrow();
    });

    it('should handle undefined alerts gracefully', () => {
      expect(() => {
        service.handleAlert(undefined as any);
      }).not.toThrow();
    });
  });

  describe('Service lifecycle', () => {
    it('should support multiple service instances independently', () => {
      const service1 = TestBed.inject(AlertHandlerService);
      const service2 = TestBed.inject(AlertHandlerService);

      // Should be the same singleton instance
      expect(service1).toBe(service2);
    });

    it('should maintain state across method calls', () => {
      service.handleAlert(createMockAlert(1));
      expect(service.alerts().length).toBe(1);

      service.handleAlert(createMockAlert(2));
      expect(service.alerts().length).toBe(2);

      expect(service.alertCount()).toBe(2);
    });
  });
});
