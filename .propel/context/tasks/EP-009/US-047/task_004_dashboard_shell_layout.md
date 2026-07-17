---
id: TASK-004
title: "Dashboard Shell Layout — Sidebar Navigation, Header, Content Area"
user_story: US-047
epic: EP-009
sprint: 2
layer: Frontend / Layout
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, TASK-003, NFR-001, NFR-033, NFR-034]
---

# TASK-004: Dashboard Shell Layout — Sidebar Navigation, Header, Content Area

> **Story:** US-047 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Layout | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the persistent shell layout that wraps all authenticated feature routes. The layout consists of three regions:

1. **Sidebar** — responsive collapsible navigation with role-based menu items
2. **Header** — top bar with user avatar, display name, notifications badge, and dark mode toggle
3. **Content area** — `<router-outlet>` where lazy-loaded feature modules are projected

The layout uses Angular Material `MatSidenav` and must be fully responsive (mobile breakpoint: ≤ 768 px, side nav collapses to overlay mode). All WCAG 2.1 AA keyboard navigation requirements must be met.

The shell layout route (`/`) wraps all protected routes via a `ShellComponent`. Feature routes are children of the shell, so they receive the `authGuard` via the parent route.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/features/dashboard/shell/shell.component.ts` | Component | Shell wrapper — `MatSidenav`, header, `<router-outlet>` |
| `src/app/features/dashboard/shell/shell.component.html` | Template | Shell layout template |
| `src/app/features/dashboard/shell/shell.component.scss` | SCSS | Shell layout styles using CSS custom properties |
| `src/app/features/dashboard/shell/sidebar/sidebar.component.ts` | Component | Sidebar nav list with Angular Material `MatNavList` |
| `src/app/features/dashboard/shell/sidebar/sidebar.component.html` | Template | Nav items with `routerLink`, active state, icons |
| `src/app/features/dashboard/shell/header/header.component.ts` | Component | Header bar — user info, notifications badge, theme toggle |
| `src/app/features/dashboard/shell/header/header.component.html` | Template | Header template |
| `src/app/features/dashboard/shell/header/header.component.scss` | SCSS | Header styles |
| `src/app/features/dashboard/dashboard.routes.ts` | Routes | Dashboard feature routes including shell wrapper |
| `src/app/features/dashboard/shell/shell.component.spec.ts` | Unit test | Shell component render and navigation tests |

**Design references:**
- design.md §3.4 — `features/dashboard/` module structure
- design.md §4.1 — Angular Material 17 component library
- US-047 DoD — sidebar navigation, header with user info and notifications badge, content area
- NFR-033 — mobile-first responsive layout (≥ 320 px screen width)
- NFR-034 — WCAG 2.1 AA: keyboard navigation, ARIA landmarks

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Shell layout uses lazy-loaded `DashboardModule` chunk — contributes minimal bytes to initial load |
| Scenario 2 | Shell route loaded only after navigating to `/dashboard`; feature sub-routes remain lazy |

---

## Implementation Steps

### 1. Create `src/app/features/dashboard/dashboard.routes.ts`

```typescript
// Dashboard feature routes — root route renders the ShellComponent.
// All protected feature routes are children of the shell, inheriting authGuard.
// Design ref: design.md §3.4 — features/dashboard/

import { Routes } from '@angular/router';
import { authGuard } from '@core/auth/auth.guard';

export const DASHBOARD_ROUTES: Routes = [
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./home/dashboard-home.component').then((m) => m.DashboardHomeComponent),
      },
    ],
  },
];
```

### 2. Create `src/app/features/dashboard/shell/shell.component.ts`

```typescript
// ShellComponent — persistent authenticated layout wrapper.
// Contains MatSidenav (sidebar), HeaderComponent, and <router-outlet>.
// Responsive: sidenav is 'side' mode on desktop, 'over' mode on mobile.
//
// Design ref: US-047 DoD — sidebar navigation, header, content area

import {
  Component,
  OnInit,
  ViewChild,
  inject,
  signal,
  computed,
} from '@angular/core';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { RouterOutlet } from '@angular/router';
import { AsyncPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { SidebarComponent } from './sidebar/sidebar.component';
import { HeaderComponent } from './header/header.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    MatSidenavModule,
    RouterOutlet,
    AsyncPipe,
    SidebarComponent,
    HeaderComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent implements OnInit {
  @ViewChild('sidenav') sidenav!: MatSidenav;

  private readonly breakpointObserver = inject(BreakpointObserver);

  /** True when viewport is mobile (≤ 768px). */
  readonly isMobile = signal(false);

  /** Sidenav mode: 'side' for desktop, 'over' for mobile. */
  readonly sidenavMode = computed(() => (this.isMobile() ? 'over' : 'side'));

  /** Sidenav open state: always open on desktop, closed by default on mobile. */
  readonly sidenavOpened = computed(() => !this.isMobile());

  ngOnInit(): void {
    this.breakpointObserver
      .observe([Breakpoints.Handset, '(max-width: 768px)'])
      .pipe(takeUntilDestroyed())
      .subscribe((result) => {
        this.isMobile.set(result.matches);
      });
  }

  toggleSidenav(): void {
    this.sidenav.toggle();
  }
}
```

### 3. Create `src/app/features/dashboard/shell/shell.component.html`

```html
<!-- Shell layout: sidebar + header + content area.
     ARIA landmarks provided for screen reader navigation.
     Design ref: US-047 DoD, NFR-034 WCAG 2.1 AA keyboard navigation -->

<mat-sidenav-container class="shell-container" autosize>

  <!-- Sidebar navigation -->
  <mat-sidenav
    #sidenav
    [mode]="sidenavMode()"
    [opened]="sidenavOpened()"
    class="shell-sidenav"
    role="navigation"
    aria-label="Main navigation">
    <app-sidebar />
  </mat-sidenav>

  <!-- Main content area -->
  <mat-sidenav-content class="shell-content">

    <!-- Sticky header bar -->
    <app-header
      (menuToggle)="toggleSidenav()"
      role="banner"
      aria-label="Application header" />

    <!-- Feature module projection -->
    <main
      class="shell-main"
      id="main-content"
      tabindex="-1"
      aria-label="Main content">
      <router-outlet />
    </main>

  </mat-sidenav-content>

</mat-sidenav-container>
```

### 4. Create `src/app/features/dashboard/shell/shell.component.scss`

```scss
// Shell layout styles — uses CSS custom properties from _variables.scss

.shell-container {
  height: 100vh;
  background-color: var(--sh-surface-background);
}

.shell-sidenav {
  width: 260px;
  background-color: var(--sh-surface-sidebar);
  color: var(--sh-surface-sidebar-text);
  border-right: none;

  @media (max-width: 768px) {
    width: 280px;
  }
}

.shell-content {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.shell-main {
  flex: 1;
  overflow-y: auto;
  padding: var(--sh-spacing-lg);
  outline: none; // outline handled by :focus-visible in global styles

  @media (max-width: 768px) {
    padding: var(--sh-spacing-md);
  }
}
```

### 5. Create `src/app/features/dashboard/shell/sidebar/sidebar.component.ts`

```typescript
// SidebarComponent — renders the main navigation list.
// Icons use Material Icons ligatures.
// Active route highlighted via routerLinkActive directive.

import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';

interface NavItem {
  label: string;
  route: string;
  icon: string;
  ariaLabel: string;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, MatListModule, MatIconModule, MatDividerModule],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  readonly navItems: NavItem[] = [
    { label: 'Dashboard',   route: '/dashboard',   icon: 'dashboard',   ariaLabel: 'Go to dashboard overview' },
    { label: 'Patients',    route: '/patients',    icon: 'person',      ariaLabel: 'Go to patient list' },
    { label: 'Beds',        route: '/beds',        icon: 'bed',         ariaLabel: 'Go to bed management' },
    { label: 'Medications', route: '/medications', icon: 'medication',  ariaLabel: 'Go to medication reconciliation' },
    { label: 'Documents',   route: '/documents',   icon: 'description', ariaLabel: 'Go to documents' },
    { label: 'Analytics',   route: '/analytics',   icon: 'bar_chart',   ariaLabel: 'Go to analytics' },
  ];

  readonly adminItems: NavItem[] = [
    { label: 'Admin',       route: '/admin',       icon: 'admin_panel_settings', ariaLabel: 'Go to admin settings' },
  ];
}
```

### 6. Create `src/app/features/dashboard/shell/sidebar/sidebar.component.html`

```html
<!-- Sidebar navigation list with accessible labels.
     routerLinkActive applies 'active-link' class for visual active state.
     aria-current="page" set on active items for screen readers. -->

<div class="sidebar-header" aria-label="SmartHandoff logo">
  <mat-icon class="sidebar-logo-icon" aria-hidden="true">local_hospital</mat-icon>
  <span class="sidebar-logo-text">SmartHandoff</span>
</div>

<mat-divider />

<mat-nav-list>
  @for (item of navItems; track item.route) {
    <a
      mat-list-item
      [routerLink]="item.route"
      routerLinkActive="active-link"
      #rla="routerLinkActive"
      [attr.aria-current]="rla.isActive ? 'page' : null"
      [attr.aria-label]="item.ariaLabel">
      <mat-icon matListItemIcon aria-hidden="true">{{ item.icon }}</mat-icon>
      <span matListItemTitle>{{ item.label }}</span>
    </a>
  }
</mat-nav-list>

<mat-divider />

<mat-nav-list>
  @for (item of adminItems; track item.route) {
    <a
      mat-list-item
      [routerLink]="item.route"
      routerLinkActive="active-link"
      #rlaAdmin="routerLinkActive"
      [attr.aria-current]="rlaAdmin.isActive ? 'page' : null"
      [attr.aria-label]="item.ariaLabel">
      <mat-icon matListItemIcon aria-hidden="true">{{ item.icon }}</mat-icon>
      <span matListItemTitle>{{ item.label }}</span>
    </a>
  }
</mat-nav-list>
```

### 7. Create `src/app/features/dashboard/shell/header/header.component.ts`

```typescript
// HeaderComponent — top application bar.
// Displays: hamburger menu (mobile), app title, notification badge, user avatar, dark mode toggle.

import { Component, EventEmitter, Output, inject, signal } from '@angular/core';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatBadgeModule } from '@angular/material/badge';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ThemeService } from '@core/theme/theme.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
    MatBadgeModule,
    MatMenuModule,
    MatTooltipModule,
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
})
export class HeaderComponent {
  @Output() menuToggle = new EventEmitter<void>();

  protected readonly themeService = inject(ThemeService);

  // TODO (US-056): Replace stub with real user data from AuthService
  readonly userName = signal('Dr. Jane Smith');
  readonly userRole = signal('Attending Physician');

  // TODO (US-048): Replace with real notification count from SignalR service
  readonly notificationCount = signal(3);

  readonly isDarkMode = this.themeService.currentTheme;

  toggleTheme(): void {
    this.themeService.toggle();
  }
}
```

### 8. Create `src/app/features/dashboard/shell/header/header.component.html`

```html
<!-- Header toolbar — ARIA role="banner" applied on host in shell template.
     Keyboard-accessible: all interactive elements are focusable with visible focus rings.
     Design ref: US-047 DoD, NFR-034 WCAG 2.1 AA -->

<mat-toolbar class="header-toolbar" color="primary">

  <!-- Hamburger menu — visible on mobile only -->
  <button
    mat-icon-button
    class="header-menu-btn"
    (click)="menuToggle.emit()"
    aria-label="Toggle navigation menu"
    matTooltip="Toggle sidebar">
    <mat-icon>menu</mat-icon>
  </button>

  <span class="header-title">SmartHandoff</span>

  <span class="header-spacer" aria-hidden="true"></span>

  <!-- Notifications bell with badge -->
  <button
    mat-icon-button
    aria-label="Notifications — {{ notificationCount() }} unread"
    matTooltip="View notifications"
    [matBadge]="notificationCount() > 0 ? notificationCount() : null"
    matBadgeColor="warn"
    [matBadgeHidden]="notificationCount() === 0">
    <mat-icon>notifications</mat-icon>
  </button>

  <!-- Dark mode toggle -->
  <button
    mat-icon-button
    (click)="toggleTheme()"
    [attr.aria-label]="isDarkMode() === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"
    [matTooltip]="isDarkMode() === 'dark' ? 'Light mode' : 'Dark mode'">
    <mat-icon>{{ isDarkMode() === 'dark' ? 'light_mode' : 'dark_mode' }}</mat-icon>
  </button>

  <!-- User menu -->
  <button
    mat-button
    [matMenuTriggerFor]="userMenu"
    class="header-user-btn"
    aria-label="User account menu for {{ userName() }}">
    <mat-icon>account_circle</mat-icon>
    <span class="header-user-name">{{ userName() }}</span>
  </button>

  <mat-menu #userMenu="matMenu">
    <div class="user-menu-info" role="menuitem" aria-disabled="true">
      <strong>{{ userName() }}</strong>
      <span>{{ userRole() }}</span>
    </div>
    <mat-divider />
    <button mat-menu-item>
      <mat-icon>settings</mat-icon>
      Settings
    </button>
    <button mat-menu-item>
      <mat-icon>logout</mat-icon>
      Sign out
    </button>
  </mat-menu>

</mat-toolbar>
```

### 9. Create `src/app/features/dashboard/shell/header/header.component.scss`

```scss
.header-toolbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background-color: var(--sh-color-primary) !important;
  box-shadow: var(--sh-shadow-card);
}

.header-title {
  font-weight: 600;
  font-size: 1.1rem;
  letter-spacing: 0.01em;
  margin-left: var(--sh-spacing-sm);
}

.header-spacer {
  flex: 1 1 auto;
}

.header-menu-btn {
  @media (min-width: 769px) {
    display: none;
  }
}

.header-user-btn {
  display: flex;
  align-items: center;
  gap: var(--sh-spacing-xs);
  margin-left: var(--sh-spacing-sm);
}

.header-user-name {
  @media (max-width: 480px) {
    display: none;
  }
}

.user-menu-info {
  display: flex;
  flex-direction: column;
  padding: var(--sh-spacing-sm) var(--sh-spacing-md);
  pointer-events: none;

  span {
    font-size: 0.75rem;
    color: var(--sh-text-secondary);
  }
}
```

### 10. Create stub `DashboardHomeComponent`

```typescript
// src/app/features/dashboard/home/dashboard-home.component.ts
// Placeholder component — replaced by US-048 dashboard feature implementation.

import { Component } from '@angular/core';

@Component({
  selector: 'app-dashboard-home',
  standalone: true,
  template: `
    <section aria-label="Dashboard overview">
      <h1>Care Team Dashboard</h1>
      <p>Dashboard feature panels load here (US-048).</p>
    </section>
  `,
})
export class DashboardHomeComponent {}
```

---

## Validation Script

```bash
# Build and verify shell component is in dashboard chunk, not main
npx ng build --configuration=production --stats-json
node -e "
const stats = require('./dist/smarthandoff-angular/browser/stats.json');
const main = stats.assets.find(a => a.name.startsWith('main'));
const dashboardChunk = stats.assets.find(a => a.name.includes('dashboard'));
console.assert(dashboardChunk, 'Dashboard shell must be in its own lazy chunk');
console.log('Shell in chunk:', dashboardChunk.name, '✓');
console.log('Main chunk size:', (main.size / 1024).toFixed(1), 'KB');
"

# axe-core accessibility check (requires running app)
# Performed in TASK-006 Lighthouse + axe integration

# Shell component unit test
npx jest src/app/features/dashboard/shell --no-coverage

# Verify ARIA landmarks present in compiled HTML
npx ng build --configuration=development
grep -l "role=\"navigation\"\|role=\"banner\"\|role=\"main\"\|aria-label" \
  src/app/features/dashboard/shell/**/*.html && echo "ARIA landmarks present ✓"
```

---

## Definition of Done

- [ ] `ShellComponent` renders `MatSidenav` (sidebar), `HeaderComponent` (header), and `<router-outlet>` (content)
- [ ] Sidebar collapses to overlay mode on mobile (≤ 768 px) using `BreakpointObserver`
- [ ] Header shows user name, notifications badge (with count), dark mode toggle, and user menu
- [ ] `menuToggle` EventEmitter wires header hamburger button to `sidenav.toggle()`
- [ ] All ARIA landmarks present: `role="navigation"`, `role="banner"`, `<main>` with `id="main-content"`
- [ ] Navigation items have `aria-current="page"` on active route
- [ ] Dark mode toggle calls `ThemeService.toggle()` and updates icon
- [ ] `DashboardHomeComponent` stub renders without errors
- [ ] Shell component unit test passes
- [ ] `npx tsc --noEmit` passes with zero errors
