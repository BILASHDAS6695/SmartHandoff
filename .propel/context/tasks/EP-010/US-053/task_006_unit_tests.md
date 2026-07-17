---
id: TASK-006
title: "Unit Tests — DischargeInstructionsComponent, LanguageSwitcherService, WarningSectionDirective"
user_story: US-053
epic: EP-010
sprint: 2
layer: Frontend / Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-002, US-053/TASK-003, US-053/TASK-004]
---

# TASK-006: Unit Tests — DischargeInstructionsComponent, LanguageSwitcherService, WarningSectionDirective

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-053 DoD requires `axe-core` WCAG 2.1 AA test on the portal instructions page. The unit test
suite covers three testable units:

1. **`LanguageSwitcherService`** — signal initialisation, `switchLanguage`, `currentContent`
   fallback to English, `setTranslations` with unsupported language handling.
2. **`DischargeInstructionsComponent`** — renders correct section count; language switch re-renders
   content; loading/error states; preferred language initialised from JWT claim.
3. **`WarningSectionDirective`** — applies `warning-section` CSS class; sets `role="region"`;
   sets `aria-live="polite"`.

Tests use Angular `TestBed` with `provideHttpClientTesting()` and `axe-core` for accessibility
assertions on the rendered component DOM.

**Design references:**
- US-053 DoD — `axe-core` WCAG 2.1 AA test on portal instructions page
- design.md §4.1 — Angular 17; strict TypeScript; Angular Signals
- unit-testing-standards — core user flows only; minimal test count; strategic placement

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Test: component initialises `activeLanguage` from JWT `preferred_language=fr`; rendered text is French |
| Scenario 2 | Test: `switchLanguage('es')` on the service updates `currentContent()` synchronously |
| Scenario 3 | Test: five `<section>` elements render; each has expected `mat-icon` |
| Scenario 4 | Test: warning section host element has `warning-section` class, `role="region"`, `aria-live="polite"` |
| DoD — axe | axe-core scan on rendered component reports zero WCAG 2.1 AA violations |

---

## Implementation Steps

### 1. Create test files

```bash
touch frontend/src/app/features/patient-portal/discharge-instructions/language-switcher.service.spec.ts
touch frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.spec.ts
touch frontend/src/app/features/patient-portal/discharge-instructions/warning-section.directive.spec.ts
```

### 2. `language-switcher.service.spec.ts`

```typescript
/**
 * Unit tests for LanguageSwitcherService (US-053 TASK-003).
 *
 * Covers: signal initialisation, switchLanguage, currentContent fallback,
 * setTranslations with unsupported active language.
 */
import { TestBed } from '@angular/core/testing';
import { LanguageSwitcherService } from './language-switcher.service';
import { AuthService } from '../../../core/auth/auth.service';
import { InstructionTranslations } from './discharge-instructions.types';

const MOCK_TRANSLATIONS: InstructionTranslations = {
  en: {
    medications: [{ name: 'Metoprolol', dosage: '25 mg', frequency: 'twice daily' }],
    activity: 'No heavy lifting for 4 weeks.',
    diet: 'Low-sodium diet.',
    follow_up: [{ provider: 'Cardiologist', timeframe: 'within 7 days' }],
    warning_signs: ['Chest pain', 'Shortness of breath'],
  },
  fr: {
    medications: [{ name: 'Métoprolol', dosage: '25 mg', frequency: 'deux fois par jour' }],
    activity: 'Aucun port de charges lourdes pendant 4 semaines.',
    diet: 'Régime pauvre en sodium.',
    follow_up: [{ provider: 'Cardiologue', timeframe: 'dans les 7 jours' }],
    warning_signs: ['Douleur thoracique', 'Essoufflement'],
  },
};

describe('LanguageSwitcherService', () => {
  let service: LanguageSwitcherService;
  let authSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['getPatientClaim']);
    authSpy.getPatientClaim.and.returnValue('fr'); // Simulate preferred_language=fr JWT claim

    TestBed.configureTestingModule({
      providers: [
        LanguageSwitcherService,
        { provide: AuthService, useValue: authSpy },
      ],
    });

    service = TestBed.inject(LanguageSwitcherService);
    service.setTranslations(MOCK_TRANSLATIONS);
  });

  it('should initialise activeLanguage from JWT preferred_language claim', () => {
    expect(service.activeLanguage()).toBe('fr');
  });

  it('should resolve currentContent in the active language', () => {
    const content = service.currentContent();
    expect(content?.activity).toBe('Aucun port de charges lourdes pendant 4 semaines.');
  });

  it('should switch language synchronously and update currentContent', () => {
    service.switchLanguage('en');
    expect(service.activeLanguage()).toBe('en');
    expect(service.currentContent()?.activity).toBe('No heavy lifting for 4 weeks.');
  });

  it('should fall back to English if active language is not in translations', () => {
    // Load translations that do not include 'es'
    const enOnly: InstructionTranslations = { en: MOCK_TRANSLATIONS.en };
    service.switchLanguage('es');
    service.setTranslations(enOnly);
    // setTranslations corrects to 'en' when current lang is not available
    expect(service.activeLanguage()).toBe('en');
    expect(service.currentContent()?.activity).toBe('No heavy lifting for 4 weeks.');
  });

  it('should list available languages from loaded translations', () => {
    const langs = service.availableLanguages();
    expect(langs).toContain('en');
    expect(langs).toContain('fr');
    expect(langs.length).toBe(2);
  });
});
```

### 3. `warning-section.directive.spec.ts`

```typescript
/**
 * Unit tests for WarningSectionDirective (US-053 TASK-004).
 *
 * Covers: host class binding, role attribute, aria-live attribute.
 */
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { WarningSectionDirective } from './warning-section.directive';

@Component({
  standalone: true,
  imports: [WarningSectionDirective],
  template: `<section appWarningSection id="test-section">Content</section>`,
})
class TestHostComponent {}

describe('WarningSectionDirective', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<TestHostComponent>>;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [TestHostComponent] });
    fixture = TestBed.createComponent(TestHostComponent);
    fixture.detectChanges();
  });

  it('should apply the warning-section CSS class to the host element', () => {
    const section = fixture.debugElement.query(By.css('section'));
    expect(section.nativeElement.classList).toContain('warning-section');
  });

  it('should set role="region" on the host element', () => {
    const section = fixture.debugElement.query(By.css('section'));
    expect(section.nativeElement.getAttribute('role')).toBe('region');
  });

  it('should set aria-live="polite" on the host element', () => {
    const section = fixture.debugElement.query(By.css('section'));
    expect(section.nativeElement.getAttribute('aria-live')).toBe('polite');
  });
});
```

### 4. `discharge-instructions.component.spec.ts` — axe-core integration

```typescript
/**
 * Unit + accessibility tests for DischargeInstructionsComponent (US-053 TASK-002).
 *
 * Covers: section count, icon presence, language switch re-render, axe-core WCAG 2.1 AA.
 *
 * Design refs:
 *   US-053 DoD — axe-core WCAG 2.1 AA test on portal instructions page
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import axe from 'axe-core';

import { DischargeInstructionsComponent } from './discharge-instructions.component';
import { LanguageSwitcherService } from './language-switcher.service';
import { AuthService } from '../../../core/auth/auth.service';
import { environment } from '../../../../environments/environment';

const MOCK_DOC_RESPONSE = {
  id: 'doc-001',
  encounter_id: 'enc-001',
  translations: {
    en: {
      medications: [{ name: 'Aspirin', dosage: '81 mg', frequency: 'daily' }],
      activity: 'Walk 20 minutes daily.',
      diet: 'Heart-healthy diet.',
      follow_up: [{ provider: 'PCP', timeframe: 'in 2 weeks' }],
      warning_signs: ['Chest pain', 'Dizziness'],
    },
    fr: {
      medications: [{ name: 'Aspirine', dosage: '81 mg', frequency: 'quotidiennement' }],
      activity: 'Marchez 20 minutes par jour.',
      diet: 'Régime sain pour le cœur.',
      follow_up: [{ provider: 'Médecin de famille', timeframe: 'dans 2 semaines' }],
      warning_signs: ['Douleur thoracique', 'Vertige'],
    },
  },
};

describe('DischargeInstructionsComponent', () => {
  let fixture: ComponentFixture<DischargeInstructionsComponent>;
  let httpMock: HttpTestingController;
  let authSpy: jasmine.SpyObj<AuthService>;

  beforeEach(async () => {
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['getPatientClaim']);
    authSpy.getPatientClaim.and.returnValue('fr');

    await TestBed.configureTestingModule({
      imports: [DischargeInstructionsComponent, HttpClientTestingModule],
      providers: [
        LanguageSwitcherService,
        { provide: AuthService, useValue: authSpy },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => 'enc-001' } } },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(DischargeInstructionsComponent);
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    // Flush the document HTTP request
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/enc-001/discharge`,
    );
    req.flush(MOCK_DOC_RESPONSE);
    fixture.detectChanges();
  });

  afterEach(() => httpMock.verify());

  it('should render five instruction sections', () => {
    const sections = fixture.nativeElement.querySelectorAll('.instruction-section');
    expect(sections.length).toBe(5);
  });

  it('should render French content on load when preferred_language=fr', () => {
    const bodyText = fixture.nativeElement.textContent as string;
    expect(bodyText).toContain('Marchez 20 minutes par jour.');
  });

  it('should apply warning-section class to the warning signs section', () => {
    const warnSection = fixture.nativeElement.querySelector('[appwarningsection]');
    expect(warnSection?.classList).toContain('warning-section');
  });

  it('should have correct mat-icon for each section', () => {
    const icons: NodeListOf<HTMLElement> = fixture.nativeElement.querySelectorAll('mat-icon');
    const iconNames = Array.from(icons).map((el) => el.textContent?.trim());
    expect(iconNames).toContain('medication');
    expect(iconNames).toContain('directions_walk');
    expect(iconNames).toContain('restaurant');
    expect(iconNames).toContain('calendar_today');
    expect(iconNames).toContain('warning');
  });

  it('should pass axe-core WCAG 2.1 AA accessibility check', async () => {
    const results = await axe.run(fixture.nativeElement as HTMLElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results.violations).toEqual([]);
  });
});
```

### 5. Install axe-core (if not already present)

```bash
cd frontend && npm install --save-dev axe-core @types/axe-core
```

---

## Validation

```bash
# Run all US-053 unit tests
cd frontend && npx jest --testPathPattern="discharge-instructions|language-switcher|warning-section" --verbose

# Expected output:
# LanguageSwitcherService — 5 passing
# WarningSectionDirective — 3 passing
# DischargeInstructionsComponent — 5 passing (including axe-core)
```

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-053/TASK-002 | Task | Component must be implemented before component spec can compile |
| US-053/TASK-003 | Task | `LanguageSwitcherService` must exist for service spec |
| US-053/TASK-004 | Task | `WarningSectionDirective` must exist for directive spec |
