---
id: TASK-006
title: "Implement Role-Based Rendering Guards and Sidebar Count Badge via SignalR"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Routing + Real-time
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-074, UI-008, US-048]
---

# TASK-006: Implement Role-Based Rendering Guards and Sidebar Count Badge via SignalR

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Routing + Real-time | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

Two role-based behaviours must be enforced:
1. The medication review panel is accessible to `pharmacist` and `physician` only — enforced at the route level via `RoleGuard`.
2. The document approval queue panel is rendered exclusively for `physician` — enforced via a template `*ngIf` on the dashboard.
3. The sidebar navigation item for documents must carry a `MatBadge` reflecting the live pending review count, updated via the `document_created` SignalR event (established in US-048 `SignalRService`).

This task wires together route-level guards, template-level role checks, and the real-time count badge into a cohesive role-aware navigation experience.

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **Scenario 3** | Count badge in sidebar navigation reflects queue size; updates in real time |
| **Scenario 1 / 3** | Role-based rendering: medication panel only for pharmacist/physician; document queue only for physician |

---

## Implementation Steps

### 1. Verify / Extend `RoleGuard` in `core/auth/`

`RoleGuard` was established in US-047 (TASK-003). Verify it handles the `roles` data array on the route definition. If not already implemented:

**`role.guard.ts`**

```typescript
import { inject } from '@angular/core';
import { CanActivateFn, ActivatedRouteSnapshot, Router } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Route guard that enforces role-based access control.
 * Reads `data.roles: string[]` from the route definition.
 *
 * Redirects unauthenticated users to /login.
 * Redirects authenticated users without the required role to /403.
 */
export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const requiredRoles: string[] = route.data['roles'] ?? [];

  if (!auth.isAuthenticated()) {
    return router.parseUrl('/login');
  }

  const userRoles: string[] = auth.currentUser()?.roles ?? [];
  const hasRole = requiredRoles.length === 0 || requiredRoles.some((r) => userRoles.includes(r));

  if (!hasRole) {
    return router.parseUrl('/403');
  }

  return true;
};
```

### 2. Register Medication Route with Role Guard

In `app.routes.ts` (confirm this is already set by TASK-001 — add `roleGuard` if missing):

```typescript
import { roleGuard } from './core/auth/role.guard';

{
  path: 'patients/:patientId/medications',
  loadChildren: () =>
    import('./features/medications/medications.routes').then((m) => m.MEDICATION_ROUTES),
  canActivate: [roleGuard],
  data: { roles: ['pharmacist', 'physician'] },
},
```

### 3. Wire `document_created` SignalR Event to `DocumentQueueStore`

In `core/signalr/signalr-message-handlers.service.ts` (established in US-048, TASK-002), add a handler for the `document_created` event that increments the queue count for physician users:

```typescript
import { DocumentQueueStore } from '../../features/documents/store/document-queue.store';
import { AuthService } from '../auth/auth.service';

// Injected in the class constructor / inject():
private readonly queueStore = inject(DocumentQueueStore);
private readonly auth = inject(AuthService);

// Inside the method that registers SignalR event listeners
// (called after hub connection is established):
private registerDocumentHandlers(): void {
  this.hubConnection.on('document_created', (payload: { documentId: string; status: string }) => {
    // Only increment for physicians — pharmacists do not see the approval queue
    if (
      payload.status === 'PENDING_REVIEW' &&
      this.auth.currentUser()?.roles?.includes('physician')
    ) {
      this.queueStore.increment();
    }
  });
}
```

Call `this.registerDocumentHandlers()` from the `startConnection()` or equivalent method after the connection is established.

### 4. Add `MatBadge` to Sidebar Navigation Item

In `features/dashboard/components/dashboard-shell/dashboard-shell.component.html`, update the documents nav item:

```html
<a
  mat-list-item
  routerLink="/dashboard"
  routerLinkActive="active"
  [attr.aria-label]="'Documents — ' + (pendingDocCount() > 0 ? pendingDocCount() + ' awaiting approval' : 'no pending documents')"
>
  <mat-icon
    matListItemIcon
    [matBadge]="pendingDocCount() > 0 ? pendingDocCount() : null"
    matBadgeColor="warn"
    matBadgeSize="small"
    [matBadgeHidden]="pendingDocCount() === 0"
    aria-hidden="true"
  >
    description
  </mat-icon>
  <span matListItemTitle>Documents</span>
</a>
```

In `dashboard-shell.component.ts`, inject `DocumentQueueStore` and expose the count:

```typescript
import { DocumentQueueStore } from '../../../features/documents/store/document-queue.store';

private readonly queueStore = inject(DocumentQueueStore);

/** Exposed to template for sidebar badge */
readonly pendingDocCount = this.queueStore.count;
```

### 5. Template Role Guard on Dashboard Home

In `dashboard-home.component.ts`, inject `AuthService` and expose a `isPhysician` computed signal:

```typescript
import { computed } from '@angular/core';
import { AuthService } from '../../../../core/auth/auth.service';

private readonly auth = inject(AuthService);

readonly isPhysician = computed(() =>
  this.auth.currentUser()?.roles?.includes('physician') ?? false
);

readonly isPharmacistOrPhysician = computed(() => {
  const roles = this.auth.currentUser()?.roles ?? [];
  return roles.includes('pharmacist') || roles.includes('physician');
});
```

In `dashboard-home.component.html`:

```html
<!-- Document approval queue — physician only -->
<app-document-queue
  *ngIf="isPhysician()"
  aria-label="Document approval queue"
/>
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| VERIFY / MODIFY | `src/app/core/auth/role.guard.ts` — confirm `roles` data array handling |
| MODIFY | `src/app/app.routes.ts` — add `roleGuard` and `data.roles` to medications route |
| MODIFY | `src/app/core/signalr/signalr-message-handlers.service.ts` — add `document_created` handler |
| MODIFY | `src/app/features/dashboard/components/dashboard-shell/dashboard-shell.component.html` — add `MatBadge` to nav item |
| MODIFY | `src/app/features/dashboard/components/dashboard-shell/dashboard-shell.component.ts` — inject `DocumentQueueStore` |
| MODIFY | `src/app/features/dashboard/components/dashboard-home/dashboard-home.component.ts` — add `isPhysician` signal |
| MODIFY | `src/app/features/dashboard/components/dashboard-home/dashboard-home.component.html` — role-gated panels |

---

## Validation Checklist

- [ ] Navigating to `/patients/{id}/medications` as `nurse` role redirects to `/403`
- [ ] Navigating to `/patients/{id}/medications` as `pharmacist` succeeds
- [ ] Navigating to `/patients/{id}/medications` as `physician` succeeds
- [ ] `DocumentQueueComponent` renders on `/dashboard` for `physician` role
- [ ] `DocumentQueueComponent` does NOT render for `pharmacist` role on `/dashboard`
- [ ] Sidebar badge shows count matching `DocumentQueueStore.count` signal
- [ ] Badge is hidden (`matBadgeHidden`) when count is 0
- [ ] Receiving a `document_created` SignalR event with `status=PENDING_REVIEW` increments badge count for physician
- [ ] Receiving a `document_created` event does NOT increment count for pharmacist
- [ ] `aria-label` on nav item updates with count for screen reader users

---

## Dependencies

| Dependency | Notes |
|---|---|
| US-047 | `AuthService`, `RoleGuard`, dashboard shell established |
| US-048 | `SignalRService` and `signalr-message-handlers.service.ts` operational |
| TASK-004 (this story) | `DocumentQueueStore` must exist before signal handler writes to it |
