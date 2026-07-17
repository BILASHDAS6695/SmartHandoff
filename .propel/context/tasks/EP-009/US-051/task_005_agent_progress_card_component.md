---
id: TASK-005
title: "Implement `AgentProgressCardComponent` and `agentStatusIcon` Pipe"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Shared Component + Pipe
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-072, UI-005]
---

# TASK-005: Implement `AgentProgressCardComponent` and `agentStatusIcon` Pipe

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Shared Component + Pipe | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

The patient detail page must show the status of all five AI agents per encounter: Transition Coordinator, Documentation, Medication Reconciliation, Bed Management, and Follow-up Care. Each agent displays a status icon (✓ COMPLETED, ⟳ IN_PROGRESS, ⏳ PENDING, ✗ FAILED) with a red clock overlay when SLA breach is detected. The `agentStatusIcon` pipe converts a status string to a Material icon name, keeping template logic clean. This component is reusable across any encounter-facing page.

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **Scenario 4** | "Agent Progress" card shows 5 agents with status icons ✓ COMPLETED, ⟳ IN_PROGRESS, ⏳ PENDING, ✗ FAILED; SLA breach indicated with red clock icon |

---

## Implementation Steps

### 1. Define `AgentTask` Model in `shared/models/`

**`agent-task.model.ts`**

```typescript
/**
 * Represents a single AI agent task on an encounter.
 * Received from GET /api/v1/encounters/{id}/agent-tasks or via SignalR push.
 */
export interface AgentTask {
  agentType: AgentType;
  status: AgentStatus;
  /** ISO 8601 — when the task was last updated */
  updatedAt: string;
  /** True when current timestamp exceeds SLA deadline for this agent */
  slaBreach: boolean;
  /** SLA deadline ISO 8601 */
  slaDeadline: string;
}

export type AgentStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';

export type AgentType =
  | 'TRANSITION_COORDINATOR'
  | 'DOCUMENTATION'
  | 'MEDICATION_RECONCILIATION'
  | 'BED_MANAGEMENT'
  | 'FOLLOW_UP_CARE';

/** Human-readable display name per agent type */
export const AGENT_DISPLAY_NAMES: Record<AgentType, string> = {
  TRANSITION_COORDINATOR: 'Transition Coordinator',
  DOCUMENTATION: 'Documentation',
  MEDICATION_RECONCILIATION: 'Medication Reconciliation',
  BED_MANAGEMENT: 'Bed Management',
  FOLLOW_UP_CARE: 'Follow-up Care',
};
```

### 2. Create `agentStatusIcon` Pipe in `shared/pipes/`

**`agent-status-icon.pipe.ts`**

```typescript
import { Pipe, PipeTransform } from '@angular/core';
import { AgentStatus } from '../models/agent-task.model';

/**
 * Converts an AgentStatus value to a Material icon name.
 *
 * Usage: {{ task.status | agentStatusIcon }}
 *
 * COMPLETED  → 'check_circle'
 * IN_PROGRESS → 'sync'
 * PENDING    → 'schedule'
 * FAILED     → 'cancel'
 */
@Pipe({ name: 'agentStatusIcon', standalone: true, pure: true })
export class AgentStatusIconPipe implements PipeTransform {
  private static readonly ICON_MAP: Record<AgentStatus, string> = {
    COMPLETED: 'check_circle',
    IN_PROGRESS: 'sync',
    PENDING: 'schedule',
    FAILED: 'cancel',
  };

  transform(status: AgentStatus | string): string {
    return AgentStatusIconPipe.ICON_MAP[status as AgentStatus] ?? 'help_outline';
  }
}
```

**`agent-status-icon.pipe.spec.ts`**

```typescript
import { AgentStatusIconPipe } from './agent-status-icon.pipe';

describe('AgentStatusIconPipe', () => {
  const pipe = new AgentStatusIconPipe();

  it('maps COMPLETED to check_circle', () => expect(pipe.transform('COMPLETED')).toBe('check_circle'));
  it('maps IN_PROGRESS to sync', () => expect(pipe.transform('IN_PROGRESS')).toBe('sync'));
  it('maps PENDING to schedule', () => expect(pipe.transform('PENDING')).toBe('schedule'));
  it('maps FAILED to cancel', () => expect(pipe.transform('FAILED')).toBe('cancel'));
  it('returns help_outline for unknown status', () => expect(pipe.transform('UNKNOWN')).toBe('help_outline'));
});
```

### 3. Create `AgentProgressCardComponent` in `shared/components/agent-progress-card/`

**`agent-progress-card.component.ts`**

```typescript
import {
  Component, Input, ChangeDetectionStrategy
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AgentTask, AgentStatus, AGENT_DISPLAY_NAMES } from '../../models/agent-task.model';
import { AgentStatusIconPipe } from '../../pipes/agent-status-icon.pipe';

/**
 * Reusable card displaying per-agent progress for an encounter.
 * Shows 5 agent rows with status icon, label, and SLA breach indicator.
 *
 * Usage: <app-agent-progress-card [tasks]="encounter.agentTasks" />
 */
@Component({
  selector: 'app-agent-progress-card',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatTooltipModule, AgentStatusIconPipe],
  templateUrl: './agent-progress-card.component.html',
  styleUrls: ['./agent-progress-card.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentProgressCardComponent {
  @Input({ required: true }) tasks!: AgentTask[];

  readonly agentDisplayNames = AGENT_DISPLAY_NAMES;

  /** Returns CSS class for icon colour based on status */
  statusClass(status: AgentStatus | string): string {
    const map: Record<string, string> = {
      COMPLETED: 'agent-progress__icon--completed',
      IN_PROGRESS: 'agent-progress__icon--in-progress',
      PENDING: 'agent-progress__icon--pending',
      FAILED: 'agent-progress__icon--failed',
    };
    return map[status] ?? '';
  }
}
```

**`agent-progress-card.component.html`**

```html
<div class="agent-progress" aria-label="Agent progress for this encounter">
  <h3 class="agent-progress__title">Agent Progress</h3>
  <ul class="agent-progress__list" role="list">
    <li
      *ngFor="let task of tasks; trackBy: trackByAgent"
      class="agent-progress__row"
      role="listitem"
      [attr.aria-label]="agentDisplayNames[task.agentType] + ': ' + task.status + (task.slaBreach ? ', SLA breached' : '')"
    >
      <!-- Status icon -->
      <mat-icon
        class="agent-progress__icon"
        [ngClass]="statusClass(task.status)"
        [matTooltip]="task.status"
        aria-hidden="true"
      >
        {{ task.status | agentStatusIcon }}
      </mat-icon>

      <!-- Agent label -->
      <span class="agent-progress__label">
        {{ agentDisplayNames[task.agentType] }}
      </span>

      <!-- SLA breach clock -->
      <mat-icon
        *ngIf="task.slaBreach"
        class="agent-progress__sla-icon"
        [matTooltip]="'SLA breached at ' + (task.slaDeadline | date:'HH:mm')"
        aria-label="SLA breached"
      >
        alarm
      </mat-icon>
    </li>
  </ul>
</div>
```

**`agent-progress-card.component.scss`**

```scss
.agent-progress {
  padding: 16px;
  border: 1px solid var(--mat-divider-color);
  border-radius: 8px;

  &__title {
    font-size: 14px;
    font-weight: 600;
    margin: 0 0 12px;
  }

  &__list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  &__row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__label {
    font-size: 13px;
    flex: 1;
  }

  // Status icon colours
  &__icon {
    font-size: 20px;
    width: 20px;
    height: 20px;

    &--completed  { color: var(--color-risk-low);    } // green
    &--in-progress { color: var(--mat-sys-primary);  }
    &--pending    { color: var(--mat-sys-outline);   }
    &--failed     { color: var(--color-risk-high);   } // red
  }

  // SLA breach clock — always red
  &__sla-icon {
    color: var(--color-risk-high);
    font-size: 18px;
    width: 18px;
    height: 18px;
  }
}
```

### 4. Integrate into Patient Detail Page

In `features/patients/components/patient-detail/patient-detail.component.html` (add after encounter summary):

```html
<app-agent-progress-card
  *ngIf="encounter()?.agentTasks?.length"
  [tasks]="encounter()!.agentTasks"
  class="patient-detail__agent-card"
/>
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| CREATE | `src/app/shared/models/agent-task.model.ts` |
| CREATE | `src/app/shared/pipes/agent-status-icon.pipe.ts` |
| CREATE | `src/app/shared/pipes/agent-status-icon.pipe.spec.ts` |
| CREATE | `src/app/shared/components/agent-progress-card/agent-progress-card.component.ts` |
| CREATE | `src/app/shared/components/agent-progress-card/agent-progress-card.component.html` |
| CREATE | `src/app/shared/components/agent-progress-card/agent-progress-card.component.scss` |
| MODIFY | `src/app/features/patients/components/patient-detail/patient-detail.component.html` — add `<app-agent-progress-card>` |

---

## Validation Checklist

- [ ] `agentStatusIcon` pipe maps all four statuses to correct icon names
- [ ] `agentStatusIcon` pipe spec passes for all 4 statuses + unknown fallback
- [ ] Card renders all 5 agent rows with status icons
- [ ] COMPLETED icon is green, IN_PROGRESS is primary, PENDING is outline, FAILED is red
- [ ] SLA breach rows show red alarm icon with tooltip containing breach time
- [ ] Rows without SLA breach do not show alarm icon
- [ ] Component is accessible: each `li` has descriptive `aria-label`
- [ ] `ChangeDetectionStrategy.OnPush` — no performance regressions

---

## Dependencies

| Dependency | Notes |
|---|---|
| US-049 | CSS custom properties `--color-risk-high`, `--color-risk-low` defined in theme |
| US-047 | Patient detail page scaffold exists |
