---
id: TASK-002
title: "DischargeInstructionsComponent — Sections Display with Angular Material Icons"
user_story: US-053
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-001, FR-021]
---

# TASK-002: DischargeInstructionsComponent — Sections Display with Angular Material Icons

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task builds the core `DischargeInstructionsComponent`. It fetches the patient's discharge
document via `GET /api/v1/documents/{encounter_id}/discharge`, reads `Document.translations`, and
renders the five structured sections (medications, activity, diet, follow-up, warning signs) using
Angular Material `mat-icon` with healthcare-specific icons.

The component uses Angular Signals for reactive state — `activeLanguage` signal, `translations`
signal, and a `computed` signal `currentContent` — rather than `BehaviorSubject` (US-053 Technical
Notes).

On load, the component reads `preferred_language` from the patient JWT claims (decoded by the
`AuthService` already present from US-052) and initialises `activeLanguage` to that value.

**Design references:**
- US-053 Technical Notes — `computed(() => translations[activeLanguage()] ?? translations['en'])`
- US-053 DoD — sections mapped from `Document.content`; `mat-icon` healthcare icons
- US-053 AC Scenario 1 — on load with `preferred_language=fr`, text renders in French
- design.md §3.4 — `features/patient-portal/` lazy-loaded feature module
- design.md §4.1 — Angular Material 17; Angular 17 strict mode; Angular Signals
- NFR-001 — <2 s page load; component is lazy-loaded; HTTP call uses `takeUntilDestroyed`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Component reads `preferred_language` from JWT and initialises `activeLanguage` signal; renders correct language content on first paint |
| Scenario 3 | Five sections render with correct `mat-icon` icons and section labels on 375 px viewport |

---

## Implementation Steps

### 1. Implement `discharge-instructions.component.ts`

```typescript
/**
 * DischargeInstructionsComponent — structured discharge instructions (US-053).
 *
 * Displays five instruction sections (medications, activity, diet, follow-up,
 * warning signs) with Angular Material icons. Language is driven by the
 * `activeLanguage` signal initialised from the patient's JWT preferred_language
 * claim. All content derives from a `computed` signal for zero-overhead re-renders.
 *
 * Design refs:
 *   US-053 Technical Notes  — activeLanguage signal; computed currentContent
 *   US-053 DoD              — DischargeInstructionsComponent; mat-icon healthcare icons
 *   US-053 AC Scenario 1    — preferred_language=fr renders French on load
 *   design.md §3.4          — patient-portal lazy-loaded feature module
 *   design.md §4.1          — Angular 17; Angular Material 17; strict TypeScript
 *   NFR-001                 — <2 s initial load; lazy component; minimal HTTP calls
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatDividerModule } from '@angular/material/divider';

import { AuthService } from '../../../core/auth/auth.service';
import { environment } from '../../../../environments/environment';
import {
  INSTRUCTION_SECTIONS,
  LANGUAGE_LABELS,
  InstructionTranslations,
  SupportedLanguage,
} from './discharge-instructions.types';
import { WarningSectionDirective } from './warning-section.directive';

interface DocumentResponse {
  id: string;
  encounter_id: string;
  translations: InstructionTranslations;
}

@Component({
  selector: 'app-discharge-instructions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatButtonToggleModule,
    MatCardModule,
    MatDividerModule,
    WarningSectionDirective,
  ],
  templateUrl: './discharge-instructions.component.html',
  styleUrl: './discharge-instructions.component.scss',
})
export class DischargeInstructionsComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);

  /** Section metadata (icon + label) used to drive *ngFor in template. */
  protected readonly sections = INSTRUCTION_SECTIONS;

  /** Language labels for MatButtonToggle display. */
  protected readonly languageLabels = LANGUAGE_LABELS;

  /** Currently active language for display. Initialised from JWT preferred_language. */
  protected readonly activeLanguage = signal<SupportedLanguage>('en');

  /** Loaded translations map; null until the HTTP response arrives. */
  private readonly translations = signal<InstructionTranslations | null>(null);

  /** Available languages derived from loaded translations keys. */
  protected readonly availableLanguages = computed<SupportedLanguage[]>(() => {
    const t = this.translations();
    if (!t) return ['en'];
    return Object.keys(t) as SupportedLanguage[];
  });

  /**
   * Active language content resolved from translations.
   * Falls back to English if the preferred language is not available.
   */
  protected readonly currentContent = computed(() => {
    const t = this.translations();
    if (!t) return null;
    return t[this.activeLanguage()] ?? t['en'];
  });

  /** True while the document HTTP request is in flight. */
  protected readonly isLoading = signal(true);

  /** Non-null when the document fetch fails. */
  protected readonly errorMessage = signal<string | null>(null);

  ngOnInit(): void {
    // Seed active language from patient JWT claim before HTTP call resolves
    const preferredLang = this.auth.getPatientClaim<SupportedLanguage>('preferred_language');
    if (preferredLang) {
      this.activeLanguage.set(preferredLang);
    }

    const encounterId = this.route.snapshot.paramMap.get('encounterId') ?? '';
    this.http
      .get<DocumentResponse>(
        `${environment.apiBaseUrl}/api/v1/documents/${encounterId}/discharge`,
      )
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (doc) => {
          this.translations.set(doc.translations);
          this.isLoading.set(false);
        },
        error: () => {
          this.errorMessage.set('Unable to load your discharge instructions. Please try again.');
          this.isLoading.set(false);
        },
      });
  }

  /** Called by MatButtonToggle change event to switch language. */
  protected onLanguageChange(lang: SupportedLanguage): void {
    this.activeLanguage.set(lang);
  }
}
```

### 2. Implement `discharge-instructions.component.html`

```html
<!-- Discharge Instructions Page — US-053
     Renders five structured sections with mat-icon headers.
     Language switcher at top right updates activeLanguage signal (no API call).

     Design refs:
       US-053 AC Scenario 1    — preferred_language initialised from JWT; FR shown on load
       US-053 AC Scenario 3    — five sections with icons; mobile single-column layout
       US-053 DoD              — mat-icon healthcare icons per section
       NFR-034                 — Angular Material components; WCAG 2.1 AA built-in
-->

<main class="instructions-page" aria-labelledby="instructions-heading">

  <!-- Loading state -->
  <div *ngIf="isLoading()" class="loading-container" aria-live="polite" aria-busy="true">
    <mat-spinner diameter="48" aria-label="Loading discharge instructions"></mat-spinner>
  </div>

  <!-- Error state -->
  <div *ngIf="errorMessage()" class="error-banner" role="alert">
    <mat-icon aria-hidden="true">error_outline</mat-icon>
    <span>{{ errorMessage() }}</span>
  </div>

  <!-- Instructions content -->
  <ng-container *ngIf="!isLoading() && !errorMessage() && currentContent() as content">

    <!-- Page header + language switcher -->
    <div class="instructions-header">
      <h1 id="instructions-heading" class="instructions-title">
        Your Discharge Instructions
      </h1>

      <mat-button-toggle-group
        class="language-switcher"
        [value]="activeLanguage()"
        (change)="onLanguageChange($event.value)"
        aria-label="Select language for discharge instructions"
        hideSingleSelectionIndicator>
        <mat-button-toggle
          *ngFor="let lang of availableLanguages()"
          [value]="lang"
          [attr.aria-pressed]="activeLanguage() === lang">
          {{ languageLabels[lang] }}
        </mat-button-toggle>
      </mat-button-toggle-group>
    </div>

    <!-- Instruction sections -->
    <div class="sections-container">

      <!-- Medications section -->
      <section
        *ngIf="sections[0] as meta"
        class="instruction-section"
        aria-labelledby="section-medications">
        <div class="section-header">
          <mat-icon aria-hidden="true">{{ meta.icon }}</mat-icon>
          <h2 id="section-medications" class="section-title">Your Medications</h2>
        </div>
        <mat-divider></mat-divider>
        <ul class="medication-list" aria-label="Medication list">
          <li *ngFor="let med of content.medications" class="medication-item">
            <strong>{{ med.name }}</strong> — {{ med.dosage }}, {{ med.frequency }}
            <span *ngIf="med.notes" class="med-notes">{{ med.notes }}</span>
          </li>
        </ul>
      </section>

      <!-- Activity section -->
      <section
        *ngIf="sections[1] as meta"
        class="instruction-section"
        aria-labelledby="section-activity">
        <div class="section-header">
          <mat-icon aria-hidden="true">{{ meta.icon }}</mat-icon>
          <h2 id="section-activity" class="section-title">Activity</h2>
        </div>
        <mat-divider></mat-divider>
        <p class="section-body">{{ content.activity }}</p>
      </section>

      <!-- Diet section -->
      <section
        *ngIf="sections[2] as meta"
        class="instruction-section"
        aria-labelledby="section-diet">
        <div class="section-header">
          <mat-icon aria-hidden="true">{{ meta.icon }}</mat-icon>
          <h2 id="section-diet" class="section-title">Diet</h2>
        </div>
        <mat-divider></mat-divider>
        <p class="section-body">{{ content.diet }}</p>
      </section>

      <!-- Follow-up Appointments section -->
      <section
        *ngIf="sections[3] as meta"
        class="instruction-section"
        aria-labelledby="section-followup">
        <div class="section-header">
          <mat-icon aria-hidden="true">{{ meta.icon }}</mat-icon>
          <h2 id="section-followup" class="section-title">Follow-up Appointments</h2>
        </div>
        <mat-divider></mat-divider>
        <ul class="followup-list" aria-label="Follow-up appointments">
          <li *ngFor="let appt of content.follow_up" class="followup-item">
            <strong>{{ appt.provider }}</strong> — {{ appt.timeframe }}
            <span *ngIf="appt.contact" class="followup-contact">{{ appt.contact }}</span>
          </li>
        </ul>
      </section>

      <!-- Warning Signs section — appWarningSection directive applied (TASK-004) -->
      <section
        *ngIf="sections[4] as meta"
        class="instruction-section"
        appWarningSection
        aria-labelledby="section-warning">
        <div class="section-header">
          <mat-icon aria-hidden="true" class="warning-icon">{{ meta.icon }}</mat-icon>
          <h2 id="section-warning" class="section-title">
            ⚠ Call 911 immediately if you experience:
          </h2>
        </div>
        <mat-divider></mat-divider>
        <ul class="warning-list" aria-label="Warning signs requiring immediate action" role="list">
          <li *ngFor="let sign of content.warning_signs" class="warning-item">
            {{ sign }}
          </li>
        </ul>
      </section>

    </div>
  </ng-container>

</main>
```

---

## Validation

```bash
# Compile with zero TypeScript errors
cd frontend && npx tsc --noEmit

# Run Angular dev server and navigate to /portal/instructions?encounterId=<id>
# — Verify: sections render, icons appear, preferred_language=fr shows French content
# — Verify: language switcher shows active language button highlighted
```

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-053/TASK-001 | Task | Types, INSTRUCTION_SECTIONS constant must exist before template compilation |
| US-053/TASK-004 | Task | `WarningSectionDirective` must be importable (can use a stub for now) |
| US-052/TASK-001 | Task | `AuthService.getPatientClaim()` method must exist |
