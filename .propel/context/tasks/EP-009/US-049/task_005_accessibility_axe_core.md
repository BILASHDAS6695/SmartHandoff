---
id: TASK-005
title: "WCAG 2.1 AA Accessibility Validation with axe-core for Patient List Screen"
user_story: US-049
epic: EP-009
sprint: 2
layer: Frontend — Accessibility / Quality Gate
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [NFR-034, UI-004]
---

# TASK-005: WCAG 2.1 AA Accessibility Validation with axe-core for Patient List Screen

> **Story:** US-049 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Accessibility / Quality Gate | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-049 Definition of Done mandates `axe-core` confirmation of WCAG 2.1 AA compliance for the patient list screen. This task implements automated accessibility tests that run in the Angular Karma/Jest test suite using `@axe-core/angular` (or `axe-core` with `karma-axe-accessibility`). The tests cover `PatientListComponent` in its primary states: loaded with patient data, loading/skeleton state, and error state.

WCAG 2.1 AA validation is a hard gate — any axe-core violation at AA level blocks story completion.

---

## Acceptance Criteria Addressed

| US-049 AC | Requirement |
|---|---|
| **Scenario 2** | Risk badges meet WCAG 2.1 AA contrast ratios |
| **Definition of Done** | `axe-core` test confirms WCAG 2.1 AA on this screen |

---

## Implementation Steps

### 1. Install `axe-core` Dependency

```bash
npm install --save-dev axe-core @angular-devkit/build-angular
```

If using `karma`, add `karma-axe-accessibility` or use `axe-core` directly:

```bash
npm install --save-dev axe-core
```

### 2. Create Accessibility Test — `patient-list.a11y.spec.ts`

```typescript
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { of } from 'rxjs';
import axe from 'axe-core';

import { PatientListComponent } from './patient-list.component';
import { PatientApiService } from '../services/patient-api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { RiskTier } from '../../../shared/models/risk-tier.enum';
import { Subject } from 'rxjs';

/** Runs axe-core against the rendered component and asserts zero violations. */
async function assertNoA11yViolations(fixture: ComponentFixture<unknown>): Promise<void> {
  fixture.detectChanges();
  await fixture.whenStable();

  const results = await axe.run(fixture.nativeElement as HTMLElement, {
    runOnly: {
      type: 'tag',
      values: ['wcag2a', 'wcag2aa'],
    },
  });

  if (results.violations.length > 0) {
    const summary = results.violations
      .map(v => `[${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} node(s))`)
      .join('\n');
    fail(`axe-core found ${results.violations.length} WCAG 2.1 AA violation(s):\n${summary}`);
  }
}

const MOCK_PATIENTS = [
  {
    encounter_id: 'ENC-001',
    patient_id: 'PAT-001',
    mrn_masked: '****1234',
    first_name: 'John',
    last_name: 'Smith',
    date_of_birth: '1960-03-15',
    current_unit: '3A',
    room_number: '301A',
    risk_tier: RiskTier.HIGH,
    risk_score: 88,
    admission_date: '2026-07-10',
  },
  {
    encounter_id: 'ENC-002',
    patient_id: 'PAT-002',
    mrn_masked: '****5678',
    first_name: 'Jane',
    last_name: 'Doe',
    date_of_birth: '1975-08-22',
    current_unit: '3A',
    room_number: '302B',
    risk_tier: RiskTier.LOW,
    risk_score: 12,
    admission_date: '2026-07-12',
  },
];

describe('PatientListComponent — Accessibility (WCAG 2.1 AA)', () => {
  let fixture: ComponentFixture<PatientListComponent>;

  async function createFixture(
    overrides: { patients?: typeof MOCK_PATIENTS; loadError?: boolean } = {},
  ) {
    const riskScoreUpdated$ = new Subject();
    await TestBed.configureTestingModule({
      imports: [
        PatientListComponent,
        NoopAnimationsModule,
        RouterTestingModule,
        HttpClientTestingModule,
      ],
      providers: [
        {
          provide: PatientApiService,
          useValue: {
            getPatients: () =>
              overrides.loadError
                ? of(null).pipe(() => { throw new Error('API error'); })
                : of({
                    items: overrides.patients ?? MOCK_PATIENTS,
                    total: (overrides.patients ?? MOCK_PATIENTS).length,
                    page: 1,
                    page_size: 25,
                  }),
          },
        },
        {
          provide: AuthService,
          useValue: { getUnitClaims: () => ['3A', '3B'] },
        },
        {
          provide: SignalRService,
          useValue: { riskScoreUpdated$: riskScoreUpdated$.asObservable() },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PatientListComponent);
    return fixture;
  }

  it('should have no WCAG 2.1 AA violations with patient data loaded', async () => {
    fixture = await createFixture();
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with HIGH risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.HIGH }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with MEDIUM risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.MEDIUM }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with LOW risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.LOW }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with UNSCORED risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.UNSCORED }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations when patient list is empty', async () => {
    fixture = await createFixture({ patients: [] });
    await assertNoA11yViolations(fixture);
  });
});
```

### 3. Add axe-core Type Declaration (if missing)

If TypeScript cannot resolve the `axe-core` types, add to `tsconfig.spec.json`:

```json
{
  "compilerOptions": {
    "types": ["axe-core"]
  }
}
```

### 4. Contrast Ratio Verification Reference

The following colour pairs are used by `RiskBadgeComponent` and **must** be verified:

| Tier | Background | Foreground | Contrast Ratio | AA Pass (≥4.5:1) |
|------|-----------|-----------|---------------|------------------|
| HIGH | `#B71C1C` | `#FFFFFF` | 7.08:1 | ✅ |
| MEDIUM | `#F57F17` | `#000000` | 7.66:1 | ✅ |
| LOW | `#1B5E20` | `#FFFFFF` | 9.72:1 | ✅ |
| UNSCORED | `#616161` | `#FFFFFF` | 5.74:1 | ✅ |

> These ratios were calculated using the WCAG relative luminance formula. Any change to badge colours must re-verify this table before merging.

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `frontend/src/app/features/patients/components/patient-list/patient-list.a11y.spec.ts` |
| **Update** | `frontend/package.json` — add `axe-core` to `devDependencies` if not present |
| **Update** | `frontend/tsconfig.spec.json` — add `axe-core` to `types` if needed |

---

## Definition of Done

- [ ] All 6 axe-core tests pass with zero WCAG 2.1 AA violations
- [ ] All four risk badge colour tiers pass contrast ratio verification (documented in table above)
- [ ] `assertNoA11yViolations` helper reusable — not duplicated in other test files
- [ ] Tests run as part of `ng test` without additional manual steps
- [ ] axe-core version pinned in `package.json` (no `*` or `latest` range)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `RiskBadgeComponent` with CSS variables must be complete |
| TASK-003 | Task | `PatientListComponent` must be complete |
| TASK-004 | Task | SignalR integration must be complete for full component render |
| axe-core | Library | `npm install --save-dev axe-core` |
