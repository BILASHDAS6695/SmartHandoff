---
id: TASK-003
title: "Offline Banner — Online/Offline Event Listener with MatBanner Display"
user_story: US-054
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 2h
priority: Should Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-054/TASK-002, NFR-033]
---

# TASK-003: Offline Banner — Online/Offline Event Listener with MatBanner Display

> **Story:** US-054 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-054 Scenario 2 requires that when a patient opens the portal while offline, a banner reading
"You're viewing cached instructions" is displayed. The banner must:

1. Appear automatically when the browser reports `navigator.onLine === false` or the `offline` event
   fires.
2. Dismiss automatically when the `online` event fires.
3. Be implemented using Angular Material's `MatSnackBar` (the closest equivalent to `MatBanner`
   available in Angular Material 17 — `MatBanner` is not part of the stable Angular Material API).
4. Remain accessible (WCAG 2.1 AA): `role="status"` and `aria-live="polite"` to announce the
   offline state without interrupting screen reader focus.

The online/offline state is managed by a reactive `NetworkStatusService` that exposes a
`isOffline` signal so that any component in the portal module can react to connectivity changes.

**Design references:**
- US-054 Scenario 2 — "You're viewing cached instructions" banner
- US-054 DoD — Angular Service Worker online/offline event listener → `MatBanner`
- design.md §4.1 — Angular 17; Signals; standalone components
- design.md §3.4 — `core/` for singleton services; `features/patient-portal/` for portal-specific UI
- web-accessibility-standards — `aria-live` for dynamic status regions

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 2 | Offline banner "You're viewing cached instructions" displayed when portal is opened offline |

---

## Implementation Steps

### 1. Create service and component files

```bash
touch frontend/src/app/core/network/network-status.service.ts
touch frontend/src/app/features/patient-portal/offline-banner/offline-banner.component.ts
touch frontend/src/app/features/patient-portal/offline-banner/offline-banner.component.html
touch frontend/src/app/features/patient-portal/offline-banner/offline-banner.component.scss
```

### 2. Implement `network-status.service.ts`

```typescript
/**
 * NetworkStatusService — reactive online/offline connectivity tracking (US-054).
 *
 * Exposes a readonly `isOffline` signal derived from browser `online`/`offline`
 * window events. Components import this service to conditionally render offline
 * UI elements without polling.
 *
 * Design refs:
 *   US-054 Scenario 2      — offline banner trigger
 *   design.md §3.4 core/   — singleton service boundary
 *   web-accessibility-standards — aria-live status announcement
 */
import { Injectable, OnDestroy, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class NetworkStatusService implements OnDestroy {
  /** True when the browser reports the network is unavailable. */
  readonly isOffline = signal<boolean>(!navigator.onLine);

  private readonly onOnline = (): void => this.isOffline.set(false);
  private readonly onOffline = (): void => this.isOffline.set(true);

  constructor() {
    window.addEventListener('online', this.onOnline);
    window.addEventListener('offline', this.onOffline);
  }

  ngOnDestroy(): void {
    window.removeEventListener('online', this.onOnline);
    window.removeEventListener('offline', this.onOffline);
  }
}
```

### 3. Implement `offline-banner.component.ts`

```typescript
/**
 * OfflineBannerComponent — displays an accessibility-compliant offline status
 * banner in the patient portal when network connectivity is lost (US-054).
 *
 * Renders when NetworkStatusService.isOffline() === true.
 * Dismisses automatically when connectivity is restored.
 *
 * Accessibility:
 *   role="status"     — non-intrusive live region
 *   aria-live="polite" — screen reader announces banner without interrupting focus
 *
 * Design refs:
 *   US-054 Scenario 2     — banner text "You're viewing cached instructions"
 *   US-054 DoD            — offline event listener → MatBanner equivalent
 *   web-accessibility-standards — aria-live for dynamic regions
 */
import {
  ChangeDetectionStrategy,
  Component,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { NetworkStatusService } from '../../../core/network/network-status.service';

@Component({
  selector: 'app-offline-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, MatIconModule],
  templateUrl: './offline-banner.component.html',
  styleUrl: './offline-banner.component.scss',
})
export class OfflineBannerComponent {
  protected readonly networkStatus = inject(NetworkStatusService);
}
```

### 4. Implement `offline-banner.component.html`

```html
<!--
  Offline status banner (US-054 Scenario 2).
  role="status" + aria-live="polite": non-disruptive screen reader announcement.
  @if signal: renders only when offline; automatically removed when online.
-->
@if (networkStatus.isOffline()) {
  <div
    class="offline-banner"
    role="status"
    aria-live="polite"
    aria-atomic="true"
  >
    <mat-icon aria-hidden="true" class="offline-banner__icon">wifi_off</mat-icon>
    <span class="offline-banner__message">You're viewing cached instructions</span>
  </div>
}
```

### 5. Implement `offline-banner.component.scss`

```scss
// Offline banner styles (US-054).
// Colour tokens align with Angular Material amber warning palette.
.offline-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background-color: #fff8e1; // Material amber-50
  border-left: 4px solid #ffa000; // Material amber-700
  border-radius: 4px;
  margin: 0 0 16px;
  font-size: 14px;
  color: #5d4037; // Material brown-700 — sufficient contrast on amber-50

  &__icon {
    color: #ffa000;
    font-size: 20px;
    height: 20px;
    width: 20px;
  }

  &__message {
    font-weight: 500;
  }
}
```

### 6. Add `OfflineBannerComponent` to `DischargeInstructionsComponent` template

In `discharge-instructions.component.html`, place the banner at the top of the page content,
below the route outlet header and before the language switcher:

```html
<!-- US-054: Offline status banner -->
<app-offline-banner />

<!-- Existing language switcher and sections below -->
```

Import `OfflineBannerComponent` in `DischargeInstructionsComponent`:

```typescript
imports: [
  // ... existing imports
  OfflineBannerComponent,
],
```

---

## Files Affected

| File | Action |
|---|---|
| `frontend/src/app/core/network/network-status.service.ts` | **Create** — reactive isOffline signal |
| `frontend/src/app/features/patient-portal/offline-banner/offline-banner.component.ts` | **Create** |
| `frontend/src/app/features/patient-portal/offline-banner/offline-banner.component.html` | **Create** |
| `frontend/src/app/features/patient-portal/offline-banner/offline-banner.component.scss` | **Create** |
| `frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.html` | **Modify** — add `<app-offline-banner />` |
| `frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.ts` | **Modify** — import `OfflineBannerComponent` |

---

## Validation

- [ ] Load instructions page with Chrome DevTools → Network → Offline disabled (normal): banner **not** visible
- [ ] Enable Chrome DevTools Offline → reload page: banner "You're viewing cached instructions" appears
- [ ] Re-enable network: banner disappears automatically (no page reload required)
- [ ] Screen reader (NVDA/VoiceOver): offline state announced politely without interrupting current reading position
- [ ] Axe-core scan: zero WCAG 2.1 AA violations on the banner element
- [ ] SCSS compiles without errors; banner colours pass 4.5:1 contrast ratio check
