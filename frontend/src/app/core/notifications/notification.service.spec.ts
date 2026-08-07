import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { NotificationService } from './notification.service';
import { SignalRService } from '../signalr/signalr.service';
import {
  AdtEventPayload,
  AlertCreatedPayload,
  TaskUpdatedPayload,
} from '../signalr/signalr.models';

describe('NotificationService', () => {
  let service: NotificationService;
  let taskUpdated$: Subject<TaskUpdatedPayload>;
  let alertCreated$: Subject<AlertCreatedPayload>;
  let adtEvent$: Subject<AdtEventPayload>;

  beforeEach(() => {
    taskUpdated$ = new Subject<TaskUpdatedPayload>();
    alertCreated$ = new Subject<AlertCreatedPayload>();
    adtEvent$ = new Subject<AdtEventPayload>();

    const signalRMock = {
      taskUpdated$: taskUpdated$.asObservable(),
      alertCreated$: alertCreated$.asObservable(),
      adtEvent$: adtEvent$.asObservable(),
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
  });

  it('should be created with initial wireframe notifications', () => {
    expect(service).toBeTruthy();
    expect(service.notifications().length).toBe(3);
    expect(service.unreadCount()).toBe(3);
  });

  it('should add a notification and update unread count', () => {
    service.add({ title: 'Test', tone: 'info' });
    expect(service.notifications().length).toBe(4);
    expect(service.unreadCount()).toBe(4);
  });

  it('should mark a notification as read', () => {
    const first = service.notifications()[0];
    service.markAsRead(first.id);
    expect(service.unreadCount()).toBe(2);
    expect(
      service.notifications().find((n) => n.id === first.id)?.read,
    ).toBeTrue();
  });

  it('should mark all notifications as read', () => {
    const marked = service.markAllAsRead();
    expect(marked).toBe(3);
    expect(service.unreadCount()).toBe(0);
  });

  it('should dismiss a notification', () => {
    const first = service.notifications()[0];
    service.dismiss(first.id);
    expect(service.notifications().some((n) => n.id === first.id)).toBeFalse();
  });

  it('should clear all notifications', () => {
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
});
