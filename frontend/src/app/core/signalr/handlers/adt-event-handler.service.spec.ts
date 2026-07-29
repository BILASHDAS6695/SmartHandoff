/**
 * Unit tests for AdtEventHandlerService
 * US-048 TASK-002
 */
import { TestBed } from '@angular/core/testing';
import { Signal } from '@angular/core';
import { Subject } from 'rxjs';
import { AdtEventHandlerService } from './adt-event-handler.service';
import { SignalRService } from '../signalr.service';
import { AdtEventPayload } from '../signalr.models';

describe('AdtEventHandlerService', () => {
  let service: AdtEventHandlerService;
  let signalRMock: jasmine.SpyObj<SignalRService>;
  let adtEventSubject: Subject<AdtEventPayload>;

  const createMockAdtEvent = (index: number): AdtEventPayload => ({
    eventType: ['A01', 'A02', 'A03'][index % 3],
    patientUnit: `${index}A`,
    timestamp: new Date(Date.now() + index * 1000).toISOString(),
    encounterId: `ENC-${String(index).padStart(3, '0')}`,
    patientDisplayName: `Patient ${index}`,
  });

  beforeEach(() => {
    adtEventSubject = new Subject<AdtEventPayload>();

    signalRMock = jasmine.createSpyObj('SignalRService', [], {
      adtEvent$: adtEventSubject.asObservable(),
      taskUpdated$: new Subject().asObservable(),
      alertCreated$: new Subject().asObservable(),
      bedStatusChanged$: new Subject().asObservable(),
    });

    TestBed.configureTestingModule({
      providers: [AdtEventHandlerService, { provide: SignalRService, useValue: signalRMock }],
    });

    service = TestBed.inject(AdtEventHandlerService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should initialize with empty ADT events array', () => {
    const events = service.adtEvents();
    expect(events).toEqual([]);
  });

  it('should append new ADT events to the signal', (done) => {
    const event = createMockAdtEvent(0);

    adtEventSubject.next(event);

    // Give signal time to update
    setTimeout(() => {
      const events = service.adtEvents();
      expect(events.length).toBe(1);
      expect(events[0]).toEqual(event);
      done();
    }, 0);
  });

  it('should maintain events in newest-first order', (done) => {
    const event0 = createMockAdtEvent(0);
    const event1 = createMockAdtEvent(1);
    const event2 = createMockAdtEvent(2);

    adtEventSubject.next(event0);
    adtEventSubject.next(event1);
    adtEventSubject.next(event2);

    setTimeout(() => {
      const events = service.adtEvents();
      expect(events.length).toBe(3);
      // Newest first
      expect(events[0]).toEqual(event2);
      expect(events[1]).toEqual(event1);
      expect(events[2]).toEqual(event0);
      done();
    }, 0);
  });

  it('should cap the feed at 20 events', (done) => {
    // Emit 25 events
    for (let i = 0; i < 25; i++) {
      adtEventSubject.next(createMockAdtEvent(i));
    }

    setTimeout(() => {
      const events = service.adtEvents();
      expect(events.length).toBe(20);
      // Newest events should be retained (20-24)
      expect(events[0].encounterId).toEqual('ENC-024');
      expect(events[19].encounterId).toEqual('ENC-005');
      done();
    }, 0);
  });

  it('should drop oldest events when exceeding 20 items', (done) => {
    // Fill with 20 events
    for (let i = 0; i < 20; i++) {
      adtEventSubject.next(createMockAdtEvent(i));
    }

    setTimeout(() => {
      const firstBatch = service.adtEvents();
      expect(firstBatch.length).toBe(20);

      // Add one more event
      adtEventSubject.next(createMockAdtEvent(20));

      setTimeout(() => {
        const secondBatch = service.adtEvents();
        expect(secondBatch.length).toBe(20);
        // Oldest event (ENC-000) should be gone
        expect(secondBatch.some((e) => e.encounterId === 'ENC-000')).toBeFalse();
        // Newest event (ENC-020) should be first
        expect(secondBatch[0].encounterId).toEqual('ENC-020');
        done();
      }, 0);
    }, 0);
  });

  it('should clean up subscription on destroy', () => {
    const unsubscribeSpy = spyOn(
      (service as any).sub,
      'unsubscribe',
    );
    service.ngOnDestroy();
    expect(unsubscribeSpy).toHaveBeenCalled();
  });

  it('should handle multiple rapid events without data loss', (done) => {
    const events = Array.from({ length: 10 }, (_, i) => createMockAdtEvent(i));

    events.forEach((event) => adtEventSubject.next(event));

    setTimeout(() => {
      const result = service.adtEvents();
      expect(result.length).toBe(10);
      // Verify all events are present (just in different order)
      expect(result.map((e) => e.encounterId)).toContain('ENC-000');
      expect(result.map((e) => e.encounterId)).toContain('ENC-009');
      done();
    }, 0);
  });
});
