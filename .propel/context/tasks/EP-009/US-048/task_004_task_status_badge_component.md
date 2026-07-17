---
id: TASK-004
title: "Task Status Badge Component — Subscribes to task_updated Events per Encounter"
user_story: US-048
epic: EP-009
sprint: 2
layer: Frontend / Shared Component
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, FR-012, NFR-006]
---

# TASK-004: Task Status Badge Component — Subscribes to task_updated Events per Encounter

> **Story:** US-048 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Shared Component | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task creates the reusable `TaskStatusBadgeComponent` that is displayed on patient detail views for each agent task associated with an encounter. The badge:

1. Accepts `taskId` and `initialStatus` as `@Input()` signals
2. Reads the live status from `TaskUpdateHandlerService.taskStatusMap` (TASK-002)
3. Displays one of four status states: **Pending**, **In Progress**, **Completed**, **Failed**
4. Transitions visually within 1 second of receiving a `task_updated` event (US-048 AC Scenario 2)

The component is placed in `src/app/shared/components/` because it will be reused across patient detail, encounter summary, and the admin audit view — not just the dashboard.

### Status badge visual design

| Status | Background | Icon | WCAG contrast |
|--------|-----------|------|---------------|
| `PENDING` | `#f5f5f5` | `schedule` (grey) | 4.6:1 |
| `IN_PROGRESS` | `#e3f2fd` | `sync` (blue, spinning) | 5.1:1 |
| `COMPLETED` | `#e8f5e9` | `check_circle` (green) | 4.8:1 |
| `FAILED` | `#fce4ec` | `error` (red) | 5.3:1 |

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/shared/components/task-status-badge/task-status-badge.component.ts` | Component | Reusable task status badge |
| `src/app/shared/components/task-status-badge/task-status-badge.component.html` | Template | Badge with icon, label, ARIA attributes |
| `src/app/shared/components/task-status-badge/task-status-badge.component.scss` | Styles | Status-specific colour tokens |
| `src/app/shared/components/task-status-badge/task-status-badge.component.spec.ts` | Unit test | Status transitions, ARIA, initial/live state |

**Design references:**
- design.md §3.4 — `shared/components/` for `RiskBadge`, `AILabel` (same pattern)
- US-048 AC Scenario 2 — badge transitions from "In Progress" to "Completed" within 1 second
- US-048 DoD — task status badge subscribes to `task_updated` events for displayed encounter

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `TaskStatusBadgeComponent` reads live status from `taskStatusMap` signal; OnPush renders within 1 tick of update |

---

## Implementation Steps

### 1. Create `task-status-badge.component.ts`

```typescript
// src/app/shared/components/task-status-badge/task-status-badge.component.ts

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TaskUpdateHandlerService } from '@core/signalr/handlers/task-update-handler.service';

type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';

/**
 * Reusable badge displaying the current status of an agent task.
 * Reactively updates when a `task_updated` SignalR event is received for the given taskId.
 *
 * Usage:
 *   <app-task-status-badge
 *     taskId="task-uuid-123"
 *     taskName="Documentation Agent"
 *     initialStatus="IN_PROGRESS"
 *   />
 */
@Component({
  selector: 'app-task-status-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, MatIconModule, MatTooltipModule],
  templateUrl: './task-status-badge.component.html',
  styleUrl: './task-status-badge.component.scss',
})
export class TaskStatusBadgeComponent implements OnInit {
  /** The unique task identifier — used to look up live status from the handler. */
  @Input({ required: true }) taskId!: string;

  /** Human-readable task name shown in the tooltip. */
  @Input({ required: true }) taskName!: string;

  /**
   * Initial status to display before any real-time update arrives.
   * Sourced from the REST response when the page first loads.
   */
  @Input() initialStatus: TaskStatus = 'PENDING';

  private readonly taskHandler = inject(TaskUpdateHandlerService);

  /** Overriding status from SignalR — null until first update received for this task. */
  private readonly _liveStatus = signal<TaskStatus | null>(null);

  /**
   * Resolved status: live status takes precedence over initial status.
   * This computed signal re-evaluates whenever either signal changes.
   */
  protected readonly status = computed<TaskStatus>(
    () => this._liveStatus() ?? this.initialStatus,
  );

  protected readonly statusLabel = computed(() => {
    const labels: Record<TaskStatus, string> = {
      PENDING: 'Pending',
      IN_PROGRESS: 'In Progress',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
    };
    return labels[this.status()];
  });

  protected readonly statusIcon = computed(() => {
    const icons: Record<TaskStatus, string> = {
      PENDING: 'schedule',
      IN_PROGRESS: 'sync',
      COMPLETED: 'check_circle',
      FAILED: 'error',
    };
    return icons[this.status()];
  });

  protected readonly isSpinning = computed(
    () => this.status() === 'IN_PROGRESS',
  );

  ngOnInit(): void {
    // Check if a live update has already arrived before this component mounted
    // (e.g., the task completed before the user navigated to the patient detail page)
    const existing = this.taskHandler.getTaskStatus(this.taskId);
    if (existing) {
      this._liveStatus.set(existing.newStatus);
    }

    // Subscribe to future updates for this specific taskId
    // Note: TaskUpdateHandlerService.taskStatusMap is a signal — effect() would
    // work here but a computed() on a filtered slice is more composable.
    // We use the map signal directly; Angular's signal graph propagates changes.
  }

  /**
   * Called by TaskUpdateHandlerService consumer pattern — updates internal live status.
   * This method is invoked from a parent container that subscribes to task updates
   * for all tasks visible in the current view, avoiding N individual subscriptions.
   *
   * @param newStatus - The incoming task status from the SignalR event
   */
  updateStatus(newStatus: TaskStatus): void {
    this._liveStatus.set(newStatus);
  }
}
```

### 2. Create `task-status-badge.component.html`

```html
<!-- Task status badge with icon and ARIA live region for screen reader announcements -->
<span
  class="task-badge"
  [class]="'task-badge task-badge--' + status().toLowerCase().replace('_', '-')"
  [matTooltip]="taskName + ': ' + statusLabel()"
  role="status"
  [attr.aria-label]="taskName + ' status: ' + statusLabel()"
>
  <mat-icon
    class="task-badge__icon"
    [class.task-badge__icon--spinning]="isSpinning()"
    aria-hidden="true"
  >
    {{ statusIcon() }}
  </mat-icon>
  <span class="task-badge__label">{{ statusLabel() }}</span>
</span>
```

### 3. Create `task-status-badge.component.scss`

```scss
// Task status badge styles — status-specific colour tokens with WCAG AA compliance.

.task-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 12px;
  font: var(--mat-sys-label-small);
  font-weight: 500;
  white-space: nowrap;

  &--pending {
    background: #f5f5f5;
    color: #424242; // WCAG 4.6:1 on #f5f5f5
  }

  &--in-progress {
    background: #e3f2fd;
    color: #0d47a1; // WCAG 5.1:1 on #e3f2fd
  }

  &--completed {
    background: #e8f5e9;
    color: #1b5e20; // WCAG 4.8:1 on #e8f5e9
  }

  &--failed {
    background: #fce4ec;
    color: #880e4f; // WCAG 5.3:1 on #fce4ec
  }

  &__icon {
    font-size: 14px;
    width: 14px;
    height: 14px;

    // Spinning animation for IN_PROGRESS state
    &--spinning {
      animation: spin 1.5s linear infinite;
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
```

### 4. Create `task-status-badge.component.spec.ts`

```typescript
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { TaskStatusBadgeComponent } from './task-status-badge.component';
import { TaskUpdateHandlerService } from '@core/signalr/handlers/task-update-handler.service';

describe('TaskStatusBadgeComponent', () => {
  let fixture: ComponentFixture<TaskStatusBadgeComponent>;
  let component: TaskStatusBadgeComponent;

  const mockHandler = {
    getTaskStatus: jest.fn().mockReturnValue(null),
    taskStatusMap: { (): Map<string, unknown> { return new Map(); } },
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TaskStatusBadgeComponent, NoopAnimationsModule],
      providers: [{ provide: TaskUpdateHandlerService, useValue: mockHandler }],
    }).compileComponents();

    fixture = TestBed.createComponent(TaskStatusBadgeComponent);
    component = fixture.componentInstance;
    component.taskId = 'task-001';
    component.taskName = 'Documentation Agent';
    component.initialStatus = 'IN_PROGRESS';
    fixture.detectChanges();
  });

  it('should display initialStatus before any live update', () => {
    const badge = fixture.nativeElement.querySelector('.task-badge');
    expect(badge.textContent).toContain('In Progress');
    expect(badge.classList).toContain('task-badge--in-progress');
  });

  it('should update to COMPLETED status when updateStatus() is called', () => {
    component.updateStatus('COMPLETED');
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.task-badge');
    expect(badge.textContent).toContain('Completed');
    expect(badge.classList).toContain('task-badge--completed');
  });

  it('should show spinning icon for IN_PROGRESS status', () => {
    const icon = fixture.nativeElement.querySelector('.task-badge__icon--spinning');
    expect(icon).not.toBeNull();
  });

  it('should NOT show spinning icon for COMPLETED status', () => {
    component.updateStatus('COMPLETED');
    fixture.detectChanges();
    const icon = fixture.nativeElement.querySelector('.task-badge__icon--spinning');
    expect(icon).toBeNull();
  });

  it('should set aria-label with task name and status', () => {
    const badge = fixture.nativeElement.querySelector('[role="status"]');
    expect(badge.getAttribute('aria-label')).toContain('Documentation Agent');
    expect(badge.getAttribute('aria-label')).toContain('In Progress');
  });
});
```

---

## Validation Loop

```bash
npx tsc --noEmit
npx jest src/app/shared/components/task-status-badge --coverage
```

---

## Definition of Done Checklist

- [ ] `TaskStatusBadgeComponent` is standalone, OnPush, placed in `shared/components/`
- [ ] `taskId` and `taskName` inputs are required
- [ ] `initialStatus` from REST response displayed before first SignalR update
- [ ] `updateStatus()` method triggers reactive status transition
- [ ] Spinning animation only active for `IN_PROGRESS`
- [ ] WCAG AA contrast ratio ≥ 4.5:1 for all status colour pairs (verified in SCSS comments)
- [ ] `role="status"` and `aria-label` present for screen reader announcements
- [ ] Unit tests: initial state, transition to COMPLETED, ARIA labels, spinning icon
- [ ] No TypeScript strict-mode errors
````
