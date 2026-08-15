import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { NotificationService } from './notification.service';
import { SignalRService } from '../signalr/signalr.service';
import {
  AdtEventPayload,
  AlertCreatedPayload,
  BedSuggestionCreatedPayload,
  BoardingAlertCreatedPayload,
  TaskUpdatedPayload,
} from '../signalr/signalr.models';

describe('NotificationService', () => {
  let service: NotificationService;
  let taskUpdated$: Subject<TaskUpdatedPayload>;
  let alertCreated$: Subject<AlertCreatedPayload>;
  let adtEvent$: Subject<AdtEventPayload>;
  let bedSuggestionCreated$: Subject<BedSuggestionCreatedPayload>;
  let boardingAlertCreated$: Subject<BoardingAlertCreatedPayload>;

  beforeEach(() => {
    taskUpdated$ = new Subject<TaskUpdatedPayload>();
    alertCreated$ = new Subject<AlertCreatedPayload>();
    adtEvent$ = new Subject<AdtEventPayload>();
    bedSuggestionCreated$ = new Subject<BedSuggestionCreatedPayload>();
    boardingAlertCreated$ = new Subject<BoardingAlertCreatedPayload>();

    const signalRMock = {
      taskUpdated$: taskUpdated$.asObservable(),
      alertCreated$: alertCreated$.asObservable(),
      adtEvent$: adtEvent$.asObservable(),
      bedSuggestionCreated$: bedSuggestionCreated$.asObservable(),
      boardingAlertCreated$: boardingAlertCreated$.asObservable(),
    };

    TestBed.configureTestingModule({
      providers: [
        NotificationService,
        { provide: SignalRService, useValue: signalRMock },
      ],
    });

    service = TestBed.inject(NotificationService);
  });

  afterEach(() => {
    taskUpdated$.complete();
    alertCreated$.complete();
    adtEvent$.complete();
    bedSuggestionCreated$.complete();
    boardingAlertCreated$.complete();
  });

  it('should be created with no initial notifications', () => {
    expect(service).toBeTruthy();
    expect(service.notifications().length).toBe(0);
    expect(service.unreadCount()).toBe(0);
  });

  it('should add a notification and update unread count', () => {
    service.add({ title: 'Test', tone: 'info' });
    expect(service.notifications().length).toBe(1);
    expect(service.unreadCount()).toBe(1);
  });

  it('should mark a notification as read', () => {
    service.add({ title: 'Test', tone: 'info' });
    const first = service.notifications()[0];
    service.markAsRead(first.id);
    expect(service.unreadCount()).toBe(0);
    expect(
      service.notifications().find((n) => n.id === first.id)?.read,
    ).toBeTrue();
  });

  it('should mark all notifications as read', () => {
    service.add({ title: 'One', tone: 'info' });
    service.add({ title: 'Two', tone: 'warning' });
    const marked = service.markAllAsRead();
    expect(marked).toBe(2);
    expect(service.unreadCount()).toBe(0);
  });

  it('should dismiss a notification', () => {
    service.add({ title: 'Test', tone: 'info' });
    const first = service.notifications()[0];
    service.dismiss(first.id);
    expect(service.notifications().some((n) => n.id === first.id)).toBeFalse();
  });

  it('should clear all notifications', () => {
    service.add({ title: 'Test', tone: 'info' });
    service.clear();
    expect(service.notifications().length).toBe(0);
    expect(service.unreadCount()).toBe(0);
  });

  it('should create a success notification when a task is completed', () => {
    taskUpdated$.next({
      taskId: 'task-1',
      encounterId: 'enc-1',
      taskName: 'Discharge Summary',
      previousStatus: 'IN_PROGRESS',
      newStatus: 'COMPLETED',
      completedAt: new Date().toISOString(),
    });
    expect(service.notifications()[0].title).toContain('Task completed: Discharge Summary');
    expect(service.notifications()[0].tone).toBe('success');
  });

  it('should not create a notification for non-completed task updates', () => {
    const before = service.notifications().length;
    taskUpdated$.next({
      taskId: 'task-1',
      encounterId: 'enc-1',
      taskName: 'Discharge Summary',
      previousStatus: 'PENDING',
      newStatus: 'IN_PROGRESS',
    });
    expect(service.notifications().length).toBe(before);
  });

  it('should create an error notification for critical alerts', () => {
    alertCreated$.next({
      alertId: 'alert-1',
      encounterId: 'enc-1',
      patientUnit: 'ICU',
      severity: 'CRITICAL',
      title: 'Critical medication interaction',
      message: 'Warfarin + Aspirin',
      timestamp: new Date().toISOString(),
    });
    const latest = service.notifications()[0];
    expect(latest.title).toBe('Critical medication interaction');
    expect(latest.tone).toBe('error');
  });

  it('should create an info notification for ADT events', () => {
    adtEvent$.next({
      eventType: 'A01',
      patientUnit: '3N',
      timestamp: new Date().toISOString(),
      encounterId: 'enc-1',
      patientDisplayName: 'Patel, R',
    });
    const latest = service.notifications()[0];
    expect(latest.title).toBe('ADT A01: Patel, R');
    expect(latest.tone).toBe('info');
  });

  it('should create an info notification for ED boarding bed suggestions', () => {
    bedSuggestionCreated$.next({
      taskId: 'task-1',
      patientName: 'Doe, J',
      patientUnit: '4-West',
      bedId: '4W-05',
      bestBedNumber: '4W-05',
    });
    const latest = service.notifications()[0];
    expect(latest.title).toBe('ED Boarding Bed Suggestion');
    expect(latest.message).toContain('Doe, J');
    expect(latest.tone).toBe('info');
    expect(latest.route).toBe('/beds');
  });

  it('should create an error notification for high-severity boarding alerts', () => {
    boardingAlertCreated$.next({
      alertId: 'alert-1',
      patientUnit: 'ED',
      minutesElapsed: 145,
      severity: 'HIGH',
      title: 'ED Boarding Alert',
      message: 'Patient has been waiting in ED for 145 minutes.',
    });
    const latest = service.notifications()[0];
    expect(latest.title).toBe('ED Boarding Alert');
    expect(latest.tone).toBe('error');
    expect(latest.route).toBe('/beds');
  });
});
