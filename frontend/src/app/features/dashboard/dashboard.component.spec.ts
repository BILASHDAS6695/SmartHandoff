/**
 * Unit tests for DashboardComponent.
 *
 * Tests cover:
 *   - Component initialization with encounter ID
 *   - Initial task loading
 *   - SignalR connection establishment
 *   - Real-time task update handling
 *   - Manual refresh functionality
 *   - Error handling
 *   - Computed signals (pending, in-progress, completed tasks)
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';

import { DashboardComponent } from './dashboard.component';
import { SignalRService, TaskUpdatedPayload } from '../../core/signalr';
import { EncounterTasksApiService } from '../../core/api';
import { AgentTaskResponse, TaskStatus } from '../../core/models';

describe('DashboardComponent', () => {
  let component: DashboardComponent;
  let fixture: ComponentFixture<DashboardComponent>;
  let mockSignalRService: any;
  let mockTasksApiService: any;
  let mockActivatedRoute: any;
  let taskUpdatedSubject: Subject<TaskUpdatedPayload>;

  const mockTask: AgentTaskResponse = {
    id: 'task-123',
    encounter_id: 'enc-001',
    unit_id: '3A',
    agent_type: 'DOCUMENTATION',
    target_role: 'nurse',
    status: TaskStatus.IN_PROGRESS,
    start_time: '2026-07-25T10:00:00Z',
    completed_time: null,
    started_at: null,
    payload: null,
    output: null,
  };

  beforeEach(async () => {
    taskUpdatedSubject = new Subject<TaskUpdatedPayload>();

    mockSignalRService = {
      connect: jest.fn().mockResolvedValue(undefined),
      disconnect: jest.fn().mockResolvedValue(undefined),
      taskUpdated$: taskUpdatedSubject.asObservable(),
    };

    mockTasksApiService = {
      getTasksForEncounter: jest.fn().mockReturnValue(of([mockTask])),
      getTaskById: jest.fn().mockReturnValue(of(mockTask)),
    };

    mockActivatedRoute = {
      params: of({ encounterId: 'enc-001' }),
    };

    await TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [
        { provide: SignalRService, useValue: mockSignalRService },
        { provide: EncounterTasksApiService, useValue: mockTasksApiService },
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(DashboardComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load initial tasks on init', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    expect(mockTasksApiService.getTasksForEncounter).toHaveBeenCalledWith('enc-001');
    expect(component.tasks()).toEqual([mockTask]);
    expect(component.isLoading()).toBe(false);
  });

  it('should start SignalR connection on init', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    expect(mockSignalRService.connect).toHaveBeenCalled();
    const callArg = mockSignalRService.connect.mock.calls[0][0];
    expect(callArg.roles).toBeDefined();
    expect(callArg.units).toBeDefined();
  });

  it('should update task when task_updated event is received', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    const updateEvent: TaskUpdatedPayload = {
      taskId: 'task-123',
      encounterId: 'enc-001',
      taskName: 'Documentation Agent',
      previousStatus: TaskStatus.IN_PROGRESS,
      newStatus: TaskStatus.COMPLETED,
      completedAt: '2026-07-25T11:00:00Z',
    } as TaskUpdatedPayload;

    taskUpdatedSubject.next(updateEvent);
    fixture.detectChanges();

    const updatedTask = component.tasks()[0];
    expect(updatedTask.status).toBe(TaskStatus.COMPLETED);
    expect(updatedTask.completed_time).toBe('2026-07-25T11:00:00Z');
  });

  it('should compute pending tasks correctly', async () => {
    component.tasks.set([
      { ...mockTask, status: TaskStatus.PENDING },
      { ...mockTask, id: 'task-2', status: TaskStatus.IN_PROGRESS },
    ]);

    expect(component.pendingTasks().length).toBe(1);
    expect(component.pendingTasks()[0].status).toBe(TaskStatus.PENDING);
  });

  it('should refresh tasks manually', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    mockTasksApiService.getTasksForEncounter.mockReturnValue(
      of([mockTask, { ...mockTask, id: 'task-2' }])
    );

    component.refreshTasks();
    await fixture.whenStable();

    expect(mockTasksApiService.getTasksForEncounter).toHaveBeenCalledTimes(2);
    expect(component.tasks().length).toBe(2);
  });

  it('should handle API errors gracefully', async () => {
    mockTasksApiService.getTasksForEncounter.mockReturnValue(
      throwError(() => new Error('API Error'))
    );

    fixture.detectChanges();
    await fixture.whenStable();

    expect(component.errorMessage()).toContain('Failed to initialize dashboard');
    expect(component.isLoading()).toBe(false);
  });

  it('should stop SignalR connection on destroy', () => {
    fixture.detectChanges();
    component.ngOnDestroy();

    expect(mockSignalRService.disconnect).toHaveBeenCalled();
  });

  it('should mark agents as Inactive when no tasks exist', () => {
    component.tasks.set([]);
    const statuses = component.agentStatusList();

    expect(statuses.every(s => s.status === 'Inactive')).toBe(true);
    expect(statuses.map(s => s.name)).toEqual([
      'Transition Coordinator',
      'Documentation',
      'Medication Reconciliation',
      'Bed Management',
      'Follow-up Care',
      'Patient Communications',
    ]);
  });

  it('should derive Degraded status when an agent has failed/blocked tasks', () => {
    component.tasks.set([
      {
        ...mockTask,
        id: 'task-med-1',
        agent_type: 'medication_reconciliation',
        status: 'failed',
      },
      {
        ...mockTask,
        id: 'task-med-2',
        agent_type: 'medication_reconciliation',
        status: 'blocked',
        blocked_reason: 'Patient identity unresolved',
      },
    ]);

    const medRecon = component.agentStatusList().find(
      s => s.name === 'Medication Reconciliation',
    );
    expect(medRecon?.status).toBe('Degraded');
    expect(medRecon?.alerts).toBe(2);
  });

  it('should derive Active status when latest task is completed and no issues', () => {
    component.tasks.set([
      {
        ...mockTask,
        id: 'task-doc-1',
        agent_type: 'documentation',
        status: 'completed',
        completed_time: '2026-07-25T11:00:00Z',
      },
    ]);

    const documentation = component.agentStatusList().find(
      s => s.name === 'Documentation',
    );
    expect(documentation?.status).toBe('Active');
    expect(documentation?.alerts).toBeUndefined();
  });

  it('should update agent status live when a SignalR task update arrives', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    component.tasks.set([
      {
        ...mockTask,
        id: 'task-med-1',
        agent_type: 'medication_reconciliation',
        status: 'running',
      },
    ]);

    expect(
      component.agentStatusList().find(s => s.name === 'Medication Reconciliation')
        ?.status,
    ).toBe('Active');

    const updateEvent: TaskUpdatedPayload = {
      task_id: 'task-med-1',
      encounter_id: 'enc-001',
      agent_type: 'medication_reconciliation',
      previous_status: 'running',
      new_status: 'failed',
      updated_at: '2026-07-25T12:00:00Z',
    } as unknown as TaskUpdatedPayload;

    taskUpdatedSubject.next(updateEvent);

    const medRecon = component.agentStatusList().find(
      s => s.name === 'Medication Reconciliation',
    );
    expect(medRecon?.status).toBe('Degraded');
    expect(medRecon?.alerts).toBe(1);
  });
});
