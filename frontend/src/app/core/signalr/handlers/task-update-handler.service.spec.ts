/**
 * Unit tests for TaskUpdateHandlerService
 * US-048 TASK-002
 */
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { TaskUpdateHandlerService } from './task-update-handler.service';
import { SignalRService } from '../signalr.service';
import { TaskUpdatedPayload } from '../signalr.models';

describe('TaskUpdateHandlerService', () => {
  let service: TaskUpdateHandlerService;
  let signalRMock: jasmine.SpyObj<SignalRService>;
  let taskUpdatedSubject: Subject<TaskUpdatedPayload>;

  const createMockTaskUpdate = (
    taskId: string,
    newStatus: TaskUpdatedPayload['newStatus'],
  ): TaskUpdatedPayload => ({
    taskId,
    encounterId: 'ENC-TEST-001',
    taskName: `Task: ${taskId}`,
    previousStatus: 'PENDING',
    newStatus,
    completedAt: newStatus === 'COMPLETED' ? new Date().toISOString() : undefined,
  });

  beforeEach(() => {
    taskUpdatedSubject = new Subject<TaskUpdatedPayload>();

    signalRMock = jasmine.createSpyObj('SignalRService', [], {
      adtEvent$: new Subject().asObservable(),
      taskUpdated$: taskUpdatedSubject.asObservable(),
      alertCreated$: new Subject().asObservable(),
      bedStatusChanged$: new Subject().asObservable(),
    });

    TestBed.configureTestingModule({
      providers: [TaskUpdateHandlerService, { provide: SignalRService, useValue: signalRMock }],
    });

    service = TestBed.inject(TaskUpdateHandlerService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should initialize with empty task status map', () => {
    const map = service.taskStatusMap();
    expect(map.size).toBe(0);
  });

  it('should add new task status to the map', (done) => {
    const update = createMockTaskUpdate('task-123', 'IN_PROGRESS');

    taskUpdatedSubject.next(update);

    setTimeout(() => {
      const map = service.taskStatusMap();
      expect(map.size).toBe(1);
      expect(map.has('task-123')).toBeTrue();
      done();
    }, 0);
  });

  it('should update existing task status', (done) => {
    const update1 = createMockTaskUpdate('task-123', 'IN_PROGRESS');
    const update2 = createMockTaskUpdate('task-123', 'COMPLETED');

    taskUpdatedSubject.next(update1);

    setTimeout(() => {
      let map = service.taskStatusMap();
      expect(map.get('task-123')?.newStatus).toBe('IN_PROGRESS');

      taskUpdatedSubject.next(update2);

      setTimeout(() => {
        map = service.taskStatusMap();
        expect(map.size).toBe(1); // Still one task
        expect(map.get('task-123')?.newStatus).toBe('COMPLETED');
        done();
      }, 0);
    }, 0);
  });

  it('should handle multiple task updates', (done) => {
    const tasks = ['task-1', 'task-2', 'task-3'];
    tasks.forEach((taskId) => {
      taskUpdatedSubject.next(createMockTaskUpdate(taskId, 'IN_PROGRESS'));
    });

    setTimeout(() => {
      const map = service.taskStatusMap();
      expect(map.size).toBe(3);
      tasks.forEach((taskId) => {
        expect(map.has(taskId)).toBeTrue();
      });
      done();
    }, 0);
  });

  it('should expose getTaskStatus method for direct lookup', (done) => {
    const update = createMockTaskUpdate('task-abc', 'COMPLETED');

    taskUpdatedSubject.next(update);

    setTimeout(() => {
      const status = service.getTaskStatus('task-abc');
      expect(status).toBeTruthy();
      expect(status?.newStatus).toBe('COMPLETED');
      done();
    }, 0);
  });

  it('should return null for non-existent task status', () => {
    const status = service.getTaskStatus('non-existent-task');
    expect(status).toBeNull();
  });

  it('should preserve completedAt timestamp on completion', (done) => {
    const update = createMockTaskUpdate('task-123', 'COMPLETED');
    const expectedTimestamp = update.completedAt;

    taskUpdatedSubject.next(update);

    setTimeout(() => {
      const status = service.getTaskStatus('task-123');
      expect(status?.completedAt).toBe(expectedTimestamp);
      done();
    }, 0);
  });

  it('should not include completedAt for non-completed tasks', (done) => {
    const update = createMockTaskUpdate('task-123', 'IN_PROGRESS');

    taskUpdatedSubject.next(update);

    setTimeout(() => {
      const status = service.getTaskStatus('task-123');
      expect(status?.completedAt).toBeUndefined();
      done();
    }, 0);
  });

  it('should clean up subscription on destroy', () => {
    const unsubscribeSpy = spyOn((service as any).sub, 'unsubscribe');
    service.ngOnDestroy();
    expect(unsubscribeSpy).toHaveBeenCalled();
  });

  it('should trigger signal update for each task update', (done) => {
    let signalUpdateCount = 0;

    // Create a computed that depends on taskStatusMap to track updates
    const trackedSignal = service.taskStatusMap;

    taskUpdatedSubject.next(createMockTaskUpdate('task-1', 'PENDING'));
    taskUpdatedSubject.next(createMockTaskUpdate('task-2', 'IN_PROGRESS'));

    setTimeout(() => {
      const map = service.taskStatusMap();
      expect(map.size).toBe(2);
      done();
    }, 0);
  });
});
