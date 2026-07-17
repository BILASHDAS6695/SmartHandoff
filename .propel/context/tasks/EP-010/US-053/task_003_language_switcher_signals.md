---
id: TASK-003
title: "Language Switcher — MatButtonToggle Group with Angular Signals and <500ms Switch"
user_story: US-053
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-002, FR-022]
---

# TASK-003: Language Switcher — MatButtonToggle Group with Angular Signals and <500ms Switch

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-053 AC Scenario 2 requires that selecting a language from the switcher changes all instruction
section text within **500 ms** with no new API call if translations are already loaded. This is
achievable with a client-side Angular `computed` signal — `activeLanguage` signal update triggers
`currentContent` re-computation, which Angular's change detection renders in the same microtask.

The `MatButtonToggle` group renders only the languages present in `Document.translations` (derived
from the `availableLanguages` computed signal in TASK-002). The active language button must be
visually highlighted and the language code must be announced to screen readers.

This task focuses on the language switcher interaction layer and the performance contract.

**Design references:**
- US-053 Technical Notes — `activeLanguage` signal; `computed(() => translations[activeLanguage()] ?? translations['en'])`
- US-053 AC Scenario 2 — all text changes within 500 ms; client-side switch; no new API call
- US-053 DoD — `MatButtonToggle` group; supported languages from `Document.translations`
- design.md §4.1 — Angular 17 Signals; Angular Material 17; `ChangeDetectionStrategy.OnPush`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 2 | `activeLanguage` signal update + `computed` re-evaluation renders new language within 500 ms; no HTTP call triggered |

---

## Implementation Steps

### 1. Language switcher service (isolated testable unit)

Create `frontend/src/app/features/patient-portal/discharge-instructions/language-switcher.service.ts`:

```typescript
/**
 * LanguageSwitcherService — manages activeLanguage signal for discharge instructions.
 *
 * Isolated to its own injectable so it can be unit-tested independently of the
 * component (US-053 DoD: tested with Jasmine/Jest). The service reads the initial
 * language from the patient JWT preferred_language claim and exposes a writable
 * signal for the component to mutate.
 *
 * Design refs:
 *   US-053 Technical Notes  — Angular Signals preferred over BehaviorSubject
 *   US-053 AC Scenario 2    — client-side language switch; no API call; <500 ms
 *   design.md §4.1          — Angular 17 Signals; strict TypeScript
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../../core/auth/auth.service';
import {
  InstructionTranslations,
  SupportedLanguage,
} from './discharge-instructions.types';

@Injectable()
export class LanguageSwitcherService {
  private readonly auth = inject(AuthService);

  /** Currently selected display language. Defaults to JWT preferred_language or 'en'. */
  readonly activeLanguage = signal<SupportedLanguage>(
    this.auth.getPatientClaim<SupportedLanguage>('preferred_language') ?? 'en',
  );

  /** Loaded translations map set by the component after document fetch. */
  private readonly _translations = signal<InstructionTranslations | null>(null);

  /** Read-only translations accessor for computed signals. */
  readonly translations = this._translations.asReadonly();

  /**
   * Languages present in the loaded translations map.
   * Determines which toggle buttons to render.
   */
  readonly availableLanguages = computed<SupportedLanguage[]>(() => {
    const t = this._translations();
    if (!t) return ['en'];
    return Object.keys(t) as SupportedLanguage[];
  });

  /**
   * Resolved content for the active language.
   * Falls back to English if the preferred language key is absent.
   *
   * Angular re-evaluates this computed signal synchronously when
   * `activeLanguage` changes — ensuring the <500 ms requirement is met
   * (no async operations, no HTTP calls).
   */
  readonly currentContent = computed(() => {
    const t = this._translations();
    if (!t) return null;
    return t[this.activeLanguage()] ?? t['en'];
  });

  /** Loads translations into the service after the document HTTP call resolves. */
  setTranslations(translations: InstructionTranslations): void {
    this._translations.set(translations);
    // Ensure active language is supported by the loaded document;
    // fall back to 'en' silently if not available.
    const lang = this.activeLanguage();
    if (!translations[lang]) {
      this.activeLanguage.set('en');
    }
  }

  /**
   * Switch the active language.
   *
   * @param lang — must be a key present in availableLanguages()
   */
  switchLanguage(lang: SupportedLanguage): void {
    this.activeLanguage.set(lang);
  }
}
```

### 2. Update `DischargeInstructionsComponent` to use the service

In `discharge-instructions.component.ts`, replace inline signal definitions with the service:

```typescript
// Inject at class level (replaces individual signals defined in TASK-002)
protected readonly langSwitcher = inject(LanguageSwitcherService);

// In ngOnInit, after HTTP response:
next: (doc) => {
  this.langSwitcher.setTranslations(doc.translations);
  this.isLoading.set(false);
},

// Template bindings use langSwitcher.activeLanguage(), langSwitcher.currentContent(), etc.
```

Register the service in the component's `providers` array for component-scoped lifetime:

```typescript
@Component({
  ...
  providers: [LanguageSwitcherService],
})
```

### 3. Language switcher SCSS — toggle button styling

In `discharge-instructions.component.scss`, add switcher styles ensuring ≥44 px touch targets:

```scss
// Language switcher — US-053 DoD: touch target ≥44px; active state visually distinct
.language-switcher {
  .mat-button-toggle {
    min-width: 44px;
    min-height: 44px;
    font-weight: 600;
    font-size: 0.875rem;
  }

  .mat-button-toggle-checked {
    background-color: var(--mat-primary-500, #1976d2);
    color: #ffffff;
  }
}
```

### 4. Performance contract validation

The <500 ms requirement is guaranteed by the Signals architecture:

- `activeLanguage.set(lang)` — synchronous write (O(1))
- `currentContent` computed re-evaluation — synchronous derived state (O(1) lookup)
- Angular `OnPush` change detection schedules a single microtask render tick
- No HTTP call, no Observable subscription — pure signal reactivity

Add a performance comment in `language-switcher.service.ts`:

```typescript
/**
 * Performance: language switch latency is bounded by Angular's change detection
 * tick (typically <16 ms on modern devices). No async work, no network calls.
 * Satisfies US-053 AC Scenario 2: all text updates within 500 ms.
 */
```

---

## Validation

```bash
# Unit test the service (see TASK-006 for full test plan)
cd frontend && npx jest --testPathPattern="language-switcher.service.spec"

# Manual check in browser DevTools:
# 1. Open Network tab; filter XHR
# 2. Select a different language from the switcher
# 3. Assert: zero new network requests fired
# 4. Assert: section text changes visibly within one animation frame (<16 ms)
```

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-053/TASK-001 | Task | `SupportedLanguage`, `InstructionTranslations` types required |
| US-053/TASK-002 | Task | `DischargeInstructionsComponent` must exist to wire service into `providers` |
| FR-022 | Requirement | Multilingual content (fr, es, en) must be present in Document.translations |
