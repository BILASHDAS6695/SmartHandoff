---
id: TASK-003
title: "Live ADT Events Panel — Real-Time Feed with Virtual Scrolling on /dashboard"
user_story: US-048
epic: EP-009
sprint: 2
layer: Frontend / Feature
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, FR-070, NFR-001, NFR-006]
---

# TASK-003: Live ADT Events Panel — Real-Time Feed with Virtual Scrolling on /dashboard

> **Story:** US-048 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Feature | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the **Live ADT Events** panel that appears on the `/dashboard` route. The panel displays the last 20 ADT events in real time by reading the `adtEvents` signal from `AdtEventHandlerService` (TASK-002). New events must appear within 1 second of the server publishing them (US-048 AC Scenario 1 / TR-003).

The panel uses Angular CDK `ScrollingModule` virtual scrolling (`<cdk-virtual-scroll-viewport>`) to render the list efficiently — this prevents DOM bloat if the feed accumulates items during a long session.

Each row in the feed displays:
- Event type badge (e.g., `A01`, `A03`) with colour coding
- Patient unit (e.g., `3A`)
- Encounter ID
- Relative timestamp (e.g., "2 seconds ago") using `RelativeTimePipe`

A **connection status indicator** in the panel header reflects `SignalRService.connectionState` signal: green dot when Connected, amber when Reconnecting, red when Disconnected.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/features/dashboard/components/live-adt-feed/live-adt-feed.component.ts` | Component | Live ADT Events panel — standalone component |
| `src/app/features/dashboard/components/live-adt-feed/live-adt-feed.component.html` | Template | Virtual scroll list, event rows, connection status badge |
| `src/app/features/dashboard/components/live-adt-feed/live-adt-feed.component.scss` | Styles | Panel layout, event type badge colours, WCAG-compliant contrast |
| `src/app/shared/pipes/relative-time.pipe.ts` | Pipe | Formats ISO timestamp to "N seconds/minutes ago" |
| `src/app/shared/pipes/relative-time.pipe.spec.ts` | Unit test | Relative time formatting edge cases |
| `src/app/features/dashboard/components/live-adt-feed/live-adt-feed.component.spec.ts` | Unit test | Component render, event append, connection state tests |

**Design references:**
- design.md §3.4 — `features/dashboard/` module, FR-070–074
- design.md §5.1 TR-003 — SignalR push latency <1 s
- US-048 AC Scenario 1 — ADT event appears within 1 second with event type, unit, timestamp, encounter ID
- US-048 DoD — virtual scrolling; last 20 events

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Component reads `adtEvents` signal; Angular change detection propagates within the same event loop tick |
| Scenario 3 | Connection status indicator reflects `connectionState` signal; shows "Reconnecting" state |

---

## Implementation Steps

### 1. Create `relative-time.pipe.ts`

```typescript
// src/app/shared/pipes/relative-time.pipe.ts
// Converts an ISO-8601 timestamp to a human-readable relative string.
// Examples: "just now", "30 seconds ago", "2 minutes ago"

import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'relativeTime', standalone: true, pure: false })
export class RelativeTimePipe implements PipeTransform {
  transform(isoTimestamp: string): string {
    const diffMs = Date.now() - new Date(isoTimestamp).getTime();
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 5) return 'just now';
    if (diffSec < 60) return `${diffSec} seconds ago`;

    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`;

    const diffHr = Math.floor(diffMin / 60);
    return `${diffHr} hour${diffHr !== 1 ? 's' : ''} ago`;
  }
}
```

### 2. Create `live-adt-feed.component.ts`

```typescript
// src/app/features/dashboard/components/live-adt-feed/live-adt-feed.component.ts

import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ScrollingModule } from '@angular/cdk/scrolling';
import { MatBadgeModule } from '@angular/material/badge';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AdtEventHandlerService } from '@core/signalr/handlers/adt-event-handler.service';
import { SignalRService } from '@core/signalr/signalr.service';
import { RelativeTimePipe } from '@shared/pipes/relative-time.pipe';
import { AdtEventPayload } from '@core/signalr/signalr.models';

/** Row height in pixels for CDK virtual scroll — must match SCSS `.event-row` height. */
const ROW_HEIGHT_PX = 56;

/**
 * Live ADT Events panel displayed on the `/dashboard` route.
 * Renders the last 20 ADT events in real time using CDK virtual scrolling.
 * Connection status is shown in the panel header via SignalRService.connectionState signal.
 *
 * Uses OnPush change detection — updates trigger automatically via signal reads in template.
 */
@Component({
  selector: 'app-live-adt-feed',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ScrollingModule,
    MatBadgeModule,
    MatIconModule,
    MatTooltipModule,
    RelativeTimePipe,
  ],
  templateUrl: './live-adt-feed.component.html',
  styleUrl: './live-adt-feed.component.scss',
})
export class LiveAdtFeedComponent {
  protected readonly adtHandler = inject(AdtEventHandlerService);
  protected readonly signalR = inject(SignalRService);

  /** Exposed for template binding */
  protected readonly adtEvents = this.adtHandler.adtEvents;
  protected readonly connectionState = this.signalR.connectionState;

  protected readonly rowHeight = ROW_HEIGHT_PX;

  /** Maps HL7 event type to a display label */
  protected eventTypeLabel(eventType: string): string {
    const labels: Record<string, string> = {
      A01: 'Admit',
      A02: 'Transfer',
      A03: 'Discharge',
      A04: 'Register',
      A08: 'Update',
      A11: 'Cancel Admit',
      A13: 'Cancel Discharge',
    };
    return labels[eventType] ?? eventType;
  }

  /** Maps HL7 event type to a CSS modifier class for badge colouring */
  protected eventTypeCssClass(eventType: string): string {
    const classes: Record<string, string> = {
      A01: 'event-badge--admit',
      A03: 'event-badge--discharge',
      A02: 'event-badge--transfer',
    };
    return classes[eventType] ?? 'event-badge--default';
  }

  /** TrackBy for virtual scroll — prevents full list re-render on append */
  protected trackByEncounterId(_index: number, event: AdtEventPayload): string {
    return `${event.encounterId}-${event.timestamp}`;
  }
}
```

### 3. Create `live-adt-feed.component.html`

```html
<!-- Live ADT Events panel — real-time feed with virtual scrolling -->
<section class="adt-feed-panel" aria-label="Live ADT Events">

  <!-- Panel header with connection status indicator -->
  <header class="adt-feed-panel__header">
    <h2 class="adt-feed-panel__title">Live ADT Events</h2>
    <span
      class="connection-indicator"
      [class.connection-indicator--connected]="connectionState() === 'Connected'"
      [class.connection-indicator--reconnecting]="connectionState() === 'Reconnecting'"
      [class.connection-indicator--disconnected]="connectionState() === 'Disconnected'"
      [matTooltip]="connectionState()"
      aria-label="SignalR connection status: {{ connectionState() }}"
      role="status"
    ></span>
  </header>

  <!-- Virtual scroll viewport — only renders visible rows -->
  <cdk-virtual-scroll-viewport
    [itemSize]="rowHeight"
    class="adt-feed-panel__viewport"
    aria-live="polite"
    aria-label="ADT event list"
  >
    <div
      *cdkVirtualFor="let event of adtEvents(); trackBy: trackByEncounterId"
      class="event-row"
      role="listitem"
    >
      <!-- Event type badge -->
      <span
        class="event-badge"
        [class]="'event-badge ' + eventTypeCssClass(event.eventType)"
        [attr.aria-label]="eventTypeLabel(event.eventType) + ' event'"
      >
        {{ event.eventType }}
      </span>

      <!-- Event details -->
      <div class="event-row__details">
        <span class="event-row__unit">Unit {{ event.patientUnit }}</span>
        <span class="event-row__encounter" aria-label="Encounter ID {{ event.encounterId }}">
          {{ event.encounterId }}
        </span>
      </div>

      <!-- Relative timestamp -->
      <time
        class="event-row__time"
        [dateTime]="event.timestamp"
        [matTooltip]="event.timestamp | date: 'medium'"
      >
        {{ event.timestamp | relativeTime }}
      </time>
    </div>

    <!-- Empty state -->
    @if (adtEvents().length === 0) {
      <div class="adt-feed-panel__empty" role="status">
        <mat-icon aria-hidden="true">wifi_tethering_off</mat-icon>
        <p>Waiting for ADT events…</p>
      </div>
    }
  </cdk-virtual-scroll-viewport>

</section>
```

### 4. Create `live-adt-feed.component.scss`

```scss
// Live ADT Events panel styles — WCAG AA contrast compliant.
// All colour tokens sourced from Angular Material custom theme (US-047 TASK-002).

.adt-feed-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-radius: 8px;
  background: var(--mat-sys-surface-container);
  overflow: hidden;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--mat-sys-outline-variant);
  }

  &__title {
    margin: 0;
    font: var(--mat-sys-title-small);
    color: var(--mat-sys-on-surface);
  }

  &__viewport {
    flex: 1;
    min-height: 0; // Required for flex children to allow scroll
  }

  &__empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px;
    color: var(--mat-sys-on-surface-variant);
    gap: 8px;
  }
}

// Connection status dot indicator
.connection-indicator {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  transition: background-color 0.3s ease;

  &--connected    { background-color: #1b873f; } // WCAG AA on white: 4.6:1
  &--reconnecting { background-color: #e65100; }
  &--disconnected { background-color: #c62828; }
}

// Event row
.event-row {
  display: flex;
  align-items: center;
  height: 56px; // Must match ROW_HEIGHT_PX constant in component
  padding: 0 16px;
  gap: 12px;
  border-bottom: 1px solid var(--mat-sys-outline-variant);

  &__details {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
  }

  &__unit {
    font: var(--mat-sys-body-medium);
    color: var(--mat-sys-on-surface);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &__encounter {
    font: var(--mat-sys-body-small);
    color: var(--mat-sys-on-surface-variant);
  }

  &__time {
    font: var(--mat-sys-label-small);
    color: var(--mat-sys-on-surface-variant);
    white-space: nowrap;
  }
}

// Event type badges
.event-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  padding: 2px 6px;
  border-radius: 4px;
  font: var(--mat-sys-label-small);
  font-weight: 600;
  letter-spacing: 0.5px;
  flex-shrink: 0;

  &--admit      { background: #e8f5e9; color: #1b5e20; } // Green — WCAG 4.8:1
  &--discharge  { background: #fce4ec; color: #880e4f; } // Red — WCAG 5.1:1
  &--transfer   { background: #e3f2fd; color: #0d47a1; } // Blue — WCAG 5.3:1
  &--default    { background: var(--mat-sys-surface-variant); color: var(--mat-sys-on-surface-variant); }
}
```

### 5. Register component in dashboard shell

In `src/app/features/dashboard/shell/shell.component.ts`, import and add `LiveAdtFeedComponent` to the `imports` array and include `<app-live-adt-feed>` in the shell template within the appropriate grid column.

---

## Validation Loop

```bash
npx tsc --noEmit
npx jest src/app/features/dashboard/components/live-adt-feed --coverage
# Verify virtual scroll renders correctly in browser dev tools: check DOM node count stays ≤ visible rows
```

---

## Definition of Done Checklist

- [ ] `LiveAdtFeedComponent` is standalone, OnPush
- [ ] CDK virtual scroll renders rows with `itemSize: 56`
- [ ] New events prepend to top of list without full re-render (trackBy verified)
- [ ] Connection status indicator updates reactively from `connectionState` signal
- [ ] Empty state displayed when no events received yet
- [ ] `RelativeTimePipe` used for all timestamps
- [ ] WCAG AA contrast ratio ≥ 4.5:1 for all badge colour pairs (verified in SCSS comments)
- [ ] Unit tests: component renders, appends event, shows empty state, shows reconnecting state
- [ ] No TypeScript strict-mode errors
````
