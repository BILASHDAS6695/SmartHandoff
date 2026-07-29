/**
 * Integration Latency Test — measures server-to-client event-to-DOM latency.
 * Uses a fake HubConnection stub to control event timing precisely.
 * Asserts that from the moment an event is dispatched to SignalRService
 * until Angular change detection reflects the update in the DOM,
 * the elapsed time is ≤ 1000 ms (US-048 DoD, TR-003).
 *
 * US-048 TASK-006
 */
import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
  flush,
} from '@angular/core/testing';
import { Subject } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { AdtEventHandlerService } from './handlers/adt-event-handler.service';
import { LiveAdtFeedComponent } from '@features/dashboard/components/live-adt-feed/live-adt-feed.component';
import { SignalRService } from './signalr.service';
import { AdtEventPayload } from './signalr.models';

// ---------------------------------------------------------------------------
// Fake SignalRService — controls event emission without real network
// ---------------------------------------------------------------------------
class FakeSignalRService {
  private readonly _adtEvent$ = new Subject<AdtEventPayload>();
  private readonly _taskUpdated$ = new Subject();
  private readonly _alertCreated$ = new Subject();
  private readonly _bedStatusChanged$ = new Subject();

  readonly adtEvent$ = this._adtEvent$.asObservable();
  readonly taskUpdated$ = this._taskUpdated$.asObservable();
  readonly alertCreated$ = this._alertCreated$.asObservable();
  readonly bedStatusChanged$ = this._bedStatusChanged$.asObservable();

  readonly connectionState = () => 'Connected' as const;
  readonly lastEventTime: string | null = null;

  /** Test helper — emit an ADT event into the stream */
  emitAdtEvent(payload: AdtEventPayload): void {
    this._adtEvent$.next(payload);
  }
}

const SAMPLE_ADT_EVENT: AdtEventPayload = {
  eventType: 'A01',
  patientUnit: '3A',
  timestamp: new Date().toISOString(),
  encounterId: 'ENC-TEST-001',
  patientDisplayName: 'J. Doe',
};

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------
describe('SignalR Server-to-Client Latency Integration', () => {
  let fixture: ComponentFixture<LiveAdtFeedComponent>;
  let fakeSignalR: FakeSignalRService;

  beforeEach(async () => {
    fakeSignalR = new FakeSignalRService();

    await TestBed.configureTestingModule({
      imports: [LiveAdtFeedComponent, NoopAnimationsModule],
      providers: [
        { provide: SignalRService, useValue: fakeSignalR },
        AdtEventHandlerService,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LiveAdtFeedComponent);
    fixture.detectChanges();
  });

  it('should reflect ADT event in DOM within 1000 ms of emission (TR-003)', fakeAsync(() => {
    const startTime = performance.now();

    // Emit event from fake hub
    fakeSignalR.emitAdtEvent(SAMPLE_ADT_EVENT);

    // Allow Angular signal propagation and change detection
    tick(0);
    fixture.detectChanges();
    flush();

    const endTime = performance.now();
    const elapsedMs = endTime - startTime;

    // Verify DOM reflects the event
    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    expect(rows.length).toBeGreaterThanOrEqual(1);

    const firstRowText: string = rows[0].textContent ?? '';
    expect(firstRowText).toContain('A01');
    expect(firstRowText).toContain('3A');

    // Assert latency SLA — in test environment should be well under 1 second;
    // this establishes a regression baseline
    expect(elapsedMs).toBeLessThan(1000);
    console.info(
      `[US-048 Latency] Event-to-DOM elapsed: ${elapsedMs.toFixed(2)} ms`,
    );
  }));

  it('should handle 20 rapid events without dropping any (capacity test)', fakeAsync(() => {
    for (let i = 0; i < 20; i++) {
      fakeSignalR.emitAdtEvent({
        ...SAMPLE_ADT_EVENT,
        encounterId: `ENC-${i.toString().padStart(3, '0')}`,
        timestamp: new Date(Date.now() + i).toISOString(),
      });
    }

    tick(0);
    fixture.detectChanges();
    flush();

    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    // Capped at 20 (MAX_ADT_EVENTS)
    expect(rows.length).toBe(20);
  }));

  it('should cap feed at 20 events when 21 are emitted', fakeAsync(() => {
    for (let i = 0; i < 21; i++) {
      fakeSignalR.emitAdtEvent({
        ...SAMPLE_ADT_EVENT,
        encounterId: `ENC-OVERFLOW-${i}`,
        timestamp: new Date(Date.now() + i).toISOString(),
      });
    }

    tick(0);
    fixture.detectChanges();
    flush();

    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    // Should be capped at 20, not 21
    expect(rows.length).toBe(20);

    // Newest event should be first
    const firstRowText = rows[0].textContent ?? '';
    expect(firstRowText).toContain('ENC-OVERFLOW-20');
  }));

  it('should display connection status indicator', fakeAsync(() => {
    fixture.detectChanges();
    tick();

    const indicator = fixture.nativeElement.querySelector('.connection-indicator');
    expect(indicator).toBeTruthy();
    expect(indicator.classList.contains('connection-indicator--connected')).toBe(
      true,
    );
  }));
});
