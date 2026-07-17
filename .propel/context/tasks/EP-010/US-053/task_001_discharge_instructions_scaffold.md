---
id: TASK-001
title: "Discharge Instructions Feature Module Scaffold + TypeScript Section Interfaces"
user_story: US-053
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-052, FR-021, FR-022]
---

# TASK-001: Discharge Instructions Feature Module Scaffold + TypeScript Section Interfaces

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-053 requires a `DischargeInstructionsComponent` inside the `patient-portal` feature module. Before
building the component itself, this task creates the directory structure, Angular route registration,
and TypeScript interfaces that model `Document.translations` JSONB shape.

The `Document.translations` field has the shape:

```json
{
  "en": {
    "medications": [...],
    "activity": "...",
    "diet": "...",
    "follow_up": [...],
    "warning_signs": [...]
  },
  "es": { ... },
  "fr": { ... }
}
```

This task establishes the typed contracts used by all subsequent tasks so that downstream work can
import from a single canonical location — avoiding duplication (DRY principle, design.md §4.1 strict
TypeScript mode).

**Design references:**
- US-053 Technical Notes — `Document.translations` JSONB structure; supported languages
- US-053 DoD — `DischargeInstructionsComponent`; sections mapped from `Document.content`
- design.md §3.4 — `features/patient-portal/` lazy-loaded feature module
- design.md §4.1 — Angular 17; strict TypeScript mode

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Types define `preferred_language` contract consumed by the component on load |
| Scenario 3 | `InstructionSection` interface enumerates all five section keys with icon metadata |

---

## Implementation Steps

### 1. Create module directory structure

```bash
mkdir -p frontend/src/app/features/patient-portal/discharge-instructions
touch frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.ts
touch frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.html
touch frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.component.scss
touch frontend/src/app/features/patient-portal/discharge-instructions/discharge-instructions.types.ts
touch frontend/src/app/features/patient-portal/discharge-instructions/warning-section.directive.ts
touch frontend/src/app/features/patient-portal/discharge-instructions/index.ts
```

### 2. Implement `discharge-instructions.types.ts`

```typescript
/**
 * TypeScript interfaces modelling Document.translations JSONB structure (US-053).
 *
 * Defines strongly-typed contracts for structured discharge instruction content
 * and the language switcher. All downstream components and directives import
 * from this file to ensure a single source of truth (DRY).
 *
 * Design refs:
 *   US-053 Technical Notes — Document.translations JSONB shape
 *   US-053 DoD             — sections: medications, activity, diet, follow_up, warning_signs
 *   design.md §4.1         — strict TypeScript mode; Angular 17
 */

/** Supported language codes backed by Document.translations keys. */
export type SupportedLanguage = 'en' | 'es' | 'fr' | 'zh' | 'ar' | 'pt';

/** A single medication item in the instructions. */
export interface MedicationItem {
  /** Drug name (brand + generic where applicable). */
  name: string;
  /** Dosage instructions in the target language. */
  dosage: string;
  /** Frequency (e.g. "twice daily"). */
  frequency: string;
  /** Special instructions (e.g. "take with food"). */
  notes?: string;
}

/** A single follow-up appointment entry. */
export interface FollowUpItem {
  /** Provider or clinic name. */
  provider: string;
  /** Recommended timeframe (e.g. "within 7 days"). */
  timeframe: string;
  /** Contact phone number or booking URL. */
  contact?: string;
}

/**
 * Structured content for a single language variant.
 *
 * Maps directly to one language key inside `Document.translations` JSONB.
 */
export interface InstructionContent {
  /** List of medication items the patient must take at home. */
  medications: MedicationItem[];
  /** Activity restrictions or allowances in plain language. */
  activity: string;
  /** Dietary guidelines in plain language. */
  diet: string;
  /** Follow-up appointment recommendations. */
  follow_up: FollowUpItem[];
  /**
   * Warning signs that require immediate medical attention.
   * Displayed with high-visibility styling (red border, amber background).
   */
  warning_signs: string[];
}

/**
 * Full translations map as stored in Document.translations JSONB.
 *
 * At minimum the 'en' key must be present; other languages are optional.
 */
export type InstructionTranslations = {
  en: InstructionContent;
} & Partial<Record<SupportedLanguage, InstructionContent>>;

/**
 * Metadata for a display section used by DischargeInstructionsComponent.
 *
 * Decouples section rendering config (icon, label key) from content data.
 */
export interface SectionMeta {
  /** Section key matching InstructionContent property name. */
  key: keyof InstructionContent;
  /** Angular Material icon name. */
  icon: string;
  /** i18n label key used to render the section heading. */
  labelKey: string;
}

/**
 * Ordered list of instruction sections rendered by the component.
 * Warning signs are last so the directive can target the final item.
 */
export const INSTRUCTION_SECTIONS: readonly SectionMeta[] = [
  { key: 'medications', icon: 'medication',       labelKey: 'instructions.sections.medications' },
  { key: 'activity',    icon: 'directions_walk',  labelKey: 'instructions.sections.activity'    },
  { key: 'diet',        icon: 'restaurant',       labelKey: 'instructions.sections.diet'         },
  { key: 'follow_up',   icon: 'calendar_today',   labelKey: 'instructions.sections.follow_up'   },
  { key: 'warning_signs', icon: 'warning',        labelKey: 'instructions.sections.warning_signs' },
] as const;

/** Display labels for the language switcher toggle group. */
export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: 'EN',
  es: 'ES',
  fr: 'FR',
  zh: '中文',
  ar: 'عر',
  pt: 'PT',
};
```

### 3. Register the component route in the patient-portal routing module

In `frontend/src/app/features/patient-portal/patient-portal.routes.ts`, add the lazy route:

```typescript
// Existing routes…
{
  path: 'instructions',
  loadComponent: () =>
    import('./discharge-instructions/discharge-instructions.component').then(
      (m) => m.DischargeInstructionsComponent,
    ),
},
```

### 4. Create barrel export `index.ts`

```typescript
export * from './discharge-instructions.types';
export { DischargeInstructionsComponent } from './discharge-instructions.component';
export { WarningSectionDirective } from './warning-section.directive';
```

---

## Validation

```bash
# TypeScript strict-mode compilation must pass with zero errors
cd frontend && npx tsc --noEmit

# Verify route is reachable (Angular dev server)
# Navigate to http://localhost:4200/portal/instructions — expect blank page (component shell)
```

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-005 | Task | patient-portal feature module and routing already exists |
| FR-021, FR-022 | Requirement | Discharge instructions content and multilingual support |
