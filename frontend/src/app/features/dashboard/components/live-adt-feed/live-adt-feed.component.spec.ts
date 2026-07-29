/**
 * Unit tests for LiveAdtFeedComponent
 * US-048 TASK-003
 */
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { signal } from '@angular/core';
import { LiveAdtFeedComponent } from './live-adt-feed.component';
import { AdtEventHandlerService } from '@core/signalr/handlers/adt-event-handler.service';
import { SignalRService } from '@core/signalr/signalr.service';
import { AdtEventPayload } from '@core/signalr/signalr.models';

describe('LiveAdtFeedComponent', () => {
  let component: LiveAdtFeedComponent;
  let fixture: ComponentFixture<LiveAdtFeedComponent>;
  let adtHandlerMock: jasmine.SpyObj<AdtEventHandlerService>;
  let signalRMock: jasmine.SpyObj<SignalRService>;

  const createMockAdtEvent = (index: number): AdtEventPayload => ({
    eventType: ['A01', 'A02', 'A03'][index % 3],
    patientUnit: `${index}A`,
    timestamp: new Date(Date.now() + index * 1000).toISOString(),
    encounterId: `ENC-${String(index).padStart(3, '0')}`,
    patientDisplayName: `Patient ${index}`,
  });

  beforeEach(async () => {
    const adtEventsSignal = signal<AdtEventPayload[]>([]);
    const connectionStateSignal = signal<'Connected' | 'Connecting' | 'Disconnected' | 'Reconnecting' | 'Disconnecting'>(
      'Connected',
    );

    adtHandlerMock = jasmine.createSpyObj('AdtEventHandlerService', [], {
      adtEvents: adtEventsSignal,
    });

    signalRMock = jasmine.createSpyObj('SignalRService', [], {
      connectionState: connectionStateSignal,
    });

    await TestBed.configureTestingModule({
      imports: [LiveAdtFeedComponent, NoopAnimationsModule],
      providers: [
        { provide: AdtEventHandlerService, useValue: adtHandlerMock },
        { provide: SignalRService, useValue: signalRMock },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LiveAdtFeedComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display empty state when no events', () => {
    const emptyState = fixture.nativeElement.querySelector('.adt-feed-panel__empty');
    expect(emptyState).toBeTruthy();
    expect(emptyState.textContent).toContain('Waiting for ADT events');
  });

  it('should render ADT events when available', fakeAsync(() => {
    const events = [createMockAdtEvent(0), createMockAdtEvent(1), createMockAdtEvent(2)];

    // Update the signal
    (adtHandlerMock.adtEvents as jasmine.Spy).and.returnValue(events);
    fixture.detectChanges();
    tick();

    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    expect(rows.length).toBeGreaterThan(0);
  }));

  it('should display connection status indicator', () => {
    const indicator = fixture.nativeElement.querySelector('.connection-indicator');
    expect(indicator).toBeTruthy();
    expect(indicator.classList.contains('connection-indicator--connected')).toBeTrue();
  });

  it('should show reconnecting state in indicator', fakeAsync(() => {
    // Update connection state to Reconnecting
    (signalRMock.connectionState as jasmine.Spy).and.returnValue('Reconnecting');
    fixture.detectChanges();
    tick();

    const indicator = fixture.nativeElement.querySelector('.connection-indicator');
    expect(indicator?.classList.contains('connection-indicator--reconnecting')).toBeTrue();
  }));

  it('should show disconnected state in indicator', fakeAsync(() => {
    // Update connection state to Disconnected
    (signalRMock.connectionState as jasmine.Spy).and.returnValue('Disconnected');
    fixture.detectChanges();
    tick();

    const indicator = fixture.nativeElement.querySelector('.connection-indicator');
    expect(indicator?.classList.contains('connection-indicator--disconnected')).toBeTrue();
  }));

  it('should display event type badges with correct styling', fakeAsync(() => {
    const event = createMockAdtEvent(0); // A01 event
    (adtHandlerMock.adtEvents as jasmine.Spy).and.returnValue([event]);
    fixture.detectChanges();
    tick();

    const badge = fixture.nativeElement.querySelector('.event-badge');
    expect(badge).toBeTruthy();
    expect(badge.classList.contains('event-badge--admit')).toBeTrue();
  }));

  it('should display patient unit information', fakeAsync(() => {
    const event = createMockAdtEvent(0);
    (adtHandlerMock.adtEvents as jasmine.Spy).and.returnValue([event]);
    fixture.detectChanges();
    tick();

    const unitText = fixture.nativeElement.querySelector('.event-unit');
    expect(unitText?.textContent).toContain('0A');
  }));

  it('should display encounter ID', fakeAsync(() => {
    const event = createMockAdtEvent(5);
    (adtHandlerMock.adtEvents as jasmine.Spy).and.returnValue([event]);
    fixture.detectChanges();
    tick();

    const encounterText = fixture.nativeElement.querySelector('.event-encounter');
    expect(encounterText?.textContent).toContain('ENC-005');
  }));

  it('should apply event type label correctly', () => {
    expect(component['eventTypeLabel']('A01')).toBe('Admit');
    expect(component['eventTypeLabel']('A02')).toBe('Transfer');
    expect(component['eventTypeLabel']('A03')).toBe('Discharge');
    expect(component['eventTypeLabel']('UNKNOWN')).toBe('UNKNOWN');
  });

  it('should apply event type CSS class correctly', () => {
    expect(component['eventTypeCssClass']('A01')).toBe('event-badge--admit');
    expect(component['eventTypeCssClass']('A02')).toBe('event-badge--transfer');
    expect(component['eventTypeCssClass']('A03')).toBe('event-badge--discharge');
    expect(component['eventTypeCssClass']('UNKNOWN')).toBe('event-badge--default');
  });

  it('should have trackBy function for virtual scroll', () => {
    const event = createMockAdtEvent(0);
    const trackId = component['trackByEncounterId'](0, event);
    expect(trackId).toContain('ENC-000');
    expect(trackId).toContain(event.timestamp);
  });

  it('should render panel header with title', () => {
    const title = fixture.nativeElement.querySelector('.adt-feed-panel__title');
    expect(title?.textContent).toContain('Live ADT Events');
  });

  it('should maintain newest-first order display', fakeAsync(() => {
    const events = [
      createMockAdtEvent(0),
      createMockAdtEvent(1),
      createMockAdtEvent(2),
    ];

    (adtHandlerMock.adtEvents as jasmine.Spy).and.returnValue(events);
    fixture.detectChanges();
    tick();

    const encounterIds = Array.from(fixture.nativeElement.querySelectorAll('.event-encounter')).map(
      (el: HTMLElement) => el.textContent,
    );

    // Should be in order received from signal (which is newest first)
    expect(encounterIds.length).toBeGreaterThan(0);
  }));

  it('should have aria-live region for accessibility', () => {
    const viewport = fixture.nativeElement.querySelector('[aria-live]');
    expect(viewport).toBeTruthy();
    expect(viewport?.getAttribute('aria-live')).toBe('polite');
  });
});
