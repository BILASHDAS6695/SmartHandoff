---
id: TASK-004
title: "PWA Manifest + Install Prompt Component — manifest.webmanifest and BeforeInstallPromptEvent"
user_story: US-054
epic: EP-010
sprint: 2
layer: Frontend / PWA
estimate: 2h
priority: Should Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-054/TASK-002, NFR-033]
---

# TASK-004: PWA Manifest + Install Prompt Component — manifest.webmanifest and BeforeInstallPromptEvent

> **Story:** US-054 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / PWA | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-054 Scenario 4 requires the patient portal to be installable as a PWA on Android Chrome (and
iOS Safari). This involves two deliverables:

1. **`manifest.webmanifest`** — tells the browser the app name, icons, and display mode so the
   "Add to Home Screen" prompt can appear and the installed app launches full-screen.
2. **`PwaInstallPromptComponent`** — captures the `BeforeInstallPromptEvent`, stores it, and shows
   an "Add to Home Screen" button so the patient can trigger installation without relying solely on
   the browser's ambient prompt.

The manifest `start_url` must be `/portal` so that launching from the home screen icon opens the
portal directly (not the staff dashboard).

**Design references:**
- US-054 Scenario 4 — `manifest.json` name, short_name, icons, display=standalone; install prompt
- US-054 DoD — `BeforeInstallPromptEvent` handled; "Add to Home Screen" button shown
- design.md §3.4 — Angular 17 PWA; `features/patient-portal/`
- design.md ADR-005 — Angular 17 PWA; service worker for offline patient instructions

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 4 | `manifest.webmanifest` has correct `name`, `short_name`, `icons` (192 px + 512 px), `display=standalone`; install prompt shown on Android Chrome; installed app launches full-screen |

---

## Implementation Steps

### 1. Create PWA icon assets

Place icon files at:
- `frontend/src/assets/icons/icon-192x192.png` (192 × 192 px)
- `frontend/src/assets/icons/icon-512x512.png` (512 × 512 px)

Icons should use the SmartHandoff brand mark on a white background. Both PNG files must be
included in `angular.json` assets array.

### 2. Implement `manifest.webmanifest`

Create or replace `frontend/src/manifest.webmanifest`:

```json
{
  "name": "SmartHandoff Patient Portal",
  "short_name": "SmartHandoff",
  "description": "Access your discharge instructions and care plan anytime.",
  "start_url": "/portal",
  "scope": "/portal",
  "display": "standalone",
  "orientation": "portrait-primary",
  "background_color": "#ffffff",
  "theme_color": "#1565C0",
  "lang": "en-US",
  "icons": [
    {
      "src": "assets/icons/icon-192x192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "assets/icons/icon-512x512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ]
}
```

### 3. Link manifest in `index.html`

```html
<!-- In frontend/src/index.html <head>: -->
<link rel="manifest" href="manifest.webmanifest" />
<meta name="theme-color" content="#1565C0" />
<!-- iOS PWA meta tags -->
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="default" />
<meta name="apple-mobile-web-app-title" content="SmartHandoff" />
<link rel="apple-touch-icon" href="assets/icons/icon-192x192.png" />
```

### 4. Implement `PwaInstallPromptService`

```bash
touch frontend/src/app/core/pwa/pwa-install-prompt.service.ts
```

```typescript
/**
 * PwaInstallPromptService — captures and defers the BeforeInstallPromptEvent
 * so the patient-portal install button can trigger it on demand (US-054).
 *
 * The browser fires BeforeInstallPromptEvent only once per session when PWA
 * install criteria are met. This service stores the event reference so that
 * the install button can call prompt() at a user-initiated moment.
 *
 * Design refs:
 *   US-054 Scenario 4  — install prompt appears; app installs to home screen
 *   US-054 DoD         — BeforeInstallPromptEvent handled; "Add to Home Screen" shown
 *   design.md ADR-005  — Angular 17 PWA
 */
import { Injectable, OnDestroy, signal } from '@angular/core';

/** Minimal interface for the non-standard BeforeInstallPromptEvent. */
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

@Injectable({ providedIn: 'root' })
export class PwaInstallPromptService implements OnDestroy {
  /** True when the deferred install prompt is available for triggering. */
  readonly canInstall = signal<boolean>(false);

  private deferredPrompt: BeforeInstallPromptEvent | null = null;

  private readonly onBeforeInstallPrompt = (event: Event): void => {
    event.preventDefault();
    this.deferredPrompt = event as BeforeInstallPromptEvent;
    this.canInstall.set(true);
  };

  private readonly onAppInstalled = (): void => {
    this.deferredPrompt = null;
    this.canInstall.set(false);
  };

  constructor() {
    window.addEventListener('beforeinstallprompt', this.onBeforeInstallPrompt);
    window.addEventListener('appinstalled', this.onAppInstalled);
  }

  /**
   * Triggers the native browser install prompt.
   * No-op if the deferred prompt is not available.
   */
  async promptInstall(): Promise<void> {
    if (!this.deferredPrompt) return;
    await this.deferredPrompt.prompt();
    const { outcome } = await this.deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      this.deferredPrompt = null;
      this.canInstall.set(false);
    }
  }

  ngOnDestroy(): void {
    window.removeEventListener('beforeinstallprompt', this.onBeforeInstallPrompt);
    window.removeEventListener('appinstalled', this.onAppInstalled);
  }
}
```

### 5. Implement `PwaInstallPromptComponent`

```bash
touch frontend/src/app/features/patient-portal/pwa-install-prompt/pwa-install-prompt.component.ts
touch frontend/src/app/features/patient-portal/pwa-install-prompt/pwa-install-prompt.component.html
touch frontend/src/app/features/patient-portal/pwa-install-prompt/pwa-install-prompt.component.scss
```

```typescript
/**
 * PwaInstallPromptComponent — renders "Add to Home Screen" button when
 * the PWA install prompt is available (US-054 Scenario 4).
 *
 * Hidden automatically when: (a) already installed, or (b) browser does not
 * support BeforeInstallPromptEvent (e.g., iOS Safari — handled by meta tags).
 */
import {
  ChangeDetectionStrategy,
  Component,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { PwaInstallPromptService } from '../../../core/pwa/pwa-install-prompt.service';

@Component({
  selector: 'app-pwa-install-prompt',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, MatButtonModule, MatIconModule],
  templateUrl: './pwa-install-prompt.component.html',
  styleUrl: './pwa-install-prompt.component.scss',
})
export class PwaInstallPromptComponent {
  protected readonly installService = inject(PwaInstallPromptService);

  onInstall(): void {
    this.installService.promptInstall();
  }
}
```

```html
<!-- pwa-install-prompt.component.html -->
<!--
  Install prompt banner (US-054 Scenario 4).
  Conditionally rendered only when canInstall signal is true.
-->
@if (installService.canInstall()) {
  <div class="install-prompt" role="complementary" aria-label="Install SmartHandoff app">
    <mat-icon aria-hidden="true" class="install-prompt__icon">install_mobile</mat-icon>
    <div class="install-prompt__text">
      <strong>Add to Home Screen</strong>
      <p>Access your instructions offline, anytime.</p>
    </div>
    <button
      mat-flat-button
      color="primary"
      aria-label="Install SmartHandoff as an app on this device"
      (click)="onInstall()"
    >
      Install
    </button>
  </div>
}
```

```scss
// pwa-install-prompt.component.scss
.install-prompt {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background-color: #e3f2fd; // Material blue-50
  border-left: 4px solid #1565c0; // Material blue-800
  border-radius: 4px;
  margin: 0 0 16px;

  &__icon {
    color: #1565c0;
    font-size: 24px;
    height: 24px;
    width: 24px;
    flex-shrink: 0;
  }

  &__text {
    flex: 1;
    font-size: 13px;
    color: #0d47a1;

    strong {
      display: block;
      font-size: 14px;
    }

    p {
      margin: 2px 0 0;
    }
  }
}
```

### 6. Add `PwaInstallPromptComponent` to the portal page shell

In the patient portal root component or `DischargeInstructionsComponent`, add the install prompt
banner at the top of the view (above the offline banner):

```html
<!-- US-054: PWA install prompt -->
<app-pwa-install-prompt />

<!-- US-054: Offline status banner -->
<app-offline-banner />

<!-- Existing content -->
```

---

## Files Affected

| File | Action |
|---|---|
| `frontend/src/manifest.webmanifest` | **Create / Replace** — PWA manifest with display=standalone, icons, start_url=/portal |
| `frontend/src/index.html` | **Modify** — add manifest link, theme-color meta, iOS PWA meta tags |
| `frontend/src/assets/icons/icon-192x192.png` | **Create** — 192 px app icon |
| `frontend/src/assets/icons/icon-512x512.png` | **Create** — 512 px app icon |
| `frontend/src/app/core/pwa/pwa-install-prompt.service.ts` | **Create** — BeforeInstallPromptEvent capture + prompt trigger |
| `frontend/src/app/features/patient-portal/pwa-install-prompt/pwa-install-prompt.component.ts` | **Create** |
| `frontend/src/app/features/patient-portal/pwa-install-prompt/pwa-install-prompt.component.html` | **Create** |
| `frontend/src/app/features/patient-portal/pwa-install-prompt/pwa-install-prompt.component.scss` | **Create** |
| `frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.html` | **Modify** — add `<app-pwa-install-prompt />` |
| `frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.ts` | **Modify** — import `PwaInstallPromptComponent` |

---

## Validation

- [ ] Chrome DevTools → Application → Manifest: manifest parsed with no errors; name, short_name, icons, start_url, display all correct
- [ ] Lighthouse PWA audit: all PWA checks pass (installable, standalone)
- [ ] Android Chrome (DevTools device emulation): "Add to Home Screen" browser prompt fires; install button in UI triggers prompt
- [ ] After install: app opens in standalone mode (no browser chrome/address bar)
- [ ] iOS Safari: `apple-mobile-web-app-capable` meta tag enables full-screen launch from home screen
- [ ] `PwaInstallPromptService.canInstall()` signal is `false` when already installed (appinstalled event)
- [ ] TypeScript compiles without errors
