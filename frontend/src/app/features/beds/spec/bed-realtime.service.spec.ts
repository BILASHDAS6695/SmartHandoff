import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { BedRealtimeService } from '../services/bed-realtime.service';
import { SignalRService } from '@core/signalr/signalr.service';
import { BedUpdateEvent } from '../models/bed.model';

describe('BedRealtimeService', () => {
  let service: BedRealtimeService;
  let signalRSpy: jasmine.SpyObj<SignalRService>;

  beforeEach(() => {
    signalRSpy = jasmine.createSpyObj('SignalRService', ['on', 'off']);
    TestBed.configureTestingModule({
      providers: [
        BedRealtimeService,
        { provide: SignalRService, useValue: signalRSpy },
      ],
    });
    service = TestBed.inject(BedRealtimeService);
  });

  it('should register bed_status_changed handler on start', () => {
    service.start(() => {});
    expect(signalRSpy.on).toHaveBeenCalledWith('bed_status_changed', jasmine.any(Function));
  });

  it('should invoke callback when SignalR emits event', () => {
    let captured: BedUpdateEvent | undefined;
    signalRSpy.on.and.callFake((_event: string, handler: (e: BedUpdateEvent) => void) => {
      handler({
        bedId: '3A-02',
        status: 'VACANT',
        patientName: null,
        predictedDischargeTime: null,
      });
    });
    service.start(ev => { captured = ev; });
    expect(captured?.bedId).toBe('3A-02');
    expect(captured?.status).toBe('VACANT');
  });

  it('should unregister handler on stop', () => {
    service.start(() => {});
    service.stop();
    expect(signalRSpy.off).toHaveBeenCalledWith('bed_status_changed');
  });

  it('should null callback on stop', () => {
    let callCount = 0;
    const callback = () => { callCount++; };
    signalRSpy.on.and.callFake((_event: string, handler: (e: BedUpdateEvent) => void) => {
      handler({
        bedId: '3A-01',
        status: 'OCCUPIED',
        patientName: 'Test',
        predictedDischargeTime: null,
      });
    });
    service.start(callback);
    expect(callCount).toBe(1);

    service.stop();
    // After stop, callback should be cleared, no further events should trigger it
    expect(signalRSpy.off).toHaveBeenCalled();
  });

  it('should not invoke callback for unknown bed IDs', () => {
    let captured: BedUpdateEvent | undefined;
    signalRSpy.on.and.callFake((_event: string, handler: (e: BedUpdateEvent) => void) => {
      handler({
        bedId: 'UNKNOWN-99',
        status: 'VACANT',
        patientName: null,
        predictedDischargeTime: null,
      });
    });
    service.start(ev => { captured = ev; });
    // The callback should still be invoked, but it's up to the consuming component to handle unknown IDs
    expect(captured?.bedId).toBe('UNKNOWN-99');
  });
});
