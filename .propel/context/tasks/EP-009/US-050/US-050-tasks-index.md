# US-050 Implementation Tasks — Render Visual Bed Board with Colour-Coded Status

> **Epic:** EP-009 — Care Team Dashboard & Real-Time Updates | **Sprint:** 2 | **Story Points:** 5
> **Status:** Draft | **Date:** 2026-07-17

---

## Task Breakdown Summary

| Task ID | Title | Layer | Effort | Dependencies |
|---------|-------|-------|--------|--------------|
| TASK-001 | BedBoardComponent — CSS Grid Layout, Colour Map, and Beds API Integration | Frontend — Component | 12 h | US-047, US-035 |
| TASK-002 | SignalR `bed_status_changed` Handler — Real-Time Cell State Updates | Frontend — Real-Time | 6 h | TASK-001, US-048 |
| TASK-003 | BedDetailPanelComponent — Slide-In Panel with RBAC Patient Info and Assign Bed Action | Frontend — Component | 8 h | TASK-001, US-036 |
| TASK-004 | Unit Filter (MatButtonToggle + sessionStorage) and WCAG Accessibility | Frontend — UX/A11y | 8 h | TASK-001 |
| TASK-005 | Unit Tests — BedBoard, BedDetailPanel, Filter, and SignalR Handler | Frontend — Testing | 6 h | TASK-001 through TASK-004 |

**Total:** 40 hours = 5 story points ✓

---

## Acceptance Criteria Coverage Matrix

| Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 | TASK-005 |
|----------|----------|----------|----------|----------|----------|
| SC1: Beds render with correct colour coding | ✅ | | | | ✅ |
| SC2: Bed cell updates within 1s of SignalR event | | ✅ | | | ✅ |
| SC3: Clicking bed cell opens detail side panel | | | ✅ | | ✅ |
| SC4: Unit filter shows/hides beds by unit | | | | ✅ | ✅ |

---

## Definition of Done Checklist

| DoD Item | Task |
|----------|------|
| `BedBoardComponent` with CSS Grid `repeat(auto-fill, minmax(120px, 1fr))` | TASK-001 |
| Colour map: VACANT=green, OCCUPIED=blue, DIRTY=orange, MAINTENANCE=grey, RESERVED=purple | TASK-001 |
| Discharge prediction column from `mv_bed_board.predicted_discharge_time` | TASK-001 |
| Skeleton loaders during initial load (UI-007) | TASK-001 |
| SignalR handler: `bed_status_changed` → update bed cell state | TASK-002 |
| `BedDetailPanelComponent` with patient info (RBAC: initials vs. full name) | TASK-003 |
| Assign Bed button for VACANT beds | TASK-003 |
| Unit filter: `MatButtonToggle` group persisted to `sessionStorage` | TASK-004 |
| Responsive: 1024px (list view) to 2560px (full floor plan grid) | TASK-004 |
| WCAG `aria-label` on every bed cell | TASK-004 |
| Code reviewed and approved | All |

---

## Implementation Order

```
TASK-001 ──► TASK-002 ──┐
                         ├──► TASK-005
             TASK-003 ──┤
             TASK-004 ──┘
```

TASK-001 is the gate for all other tasks. TASK-002, TASK-003, and TASK-004 can proceed in parallel once TASK-001 is merged. TASK-005 is written last to validate complete integration.

---

## Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Grid system | CSS Grid `repeat(auto-fill, minmax(120px, 1fr))` | Native, performant, responsive without breakpoint boilerplate |
| State management | Angular Signals (`signal<BedDto[]>`) | US-047 Angular scaffold uses Signals; avoids NgRx overhead for local component state |
| Real-time | SignalR `@microsoft/signalr` 7.x | Shared `SignalRService` from US-048; subscribe to `bed_status_changed` group |
| Colour tokens | CSS custom properties mapped via Angular `[ngClass]` | Prevents hardcoded hex values; allows theme override |
| Privacy | `MaskNamePipe` for initials; role check via `AuthService.hasRole()` | Consistent with US-050 SC3 RBAC requirement and HIPAA PHI policy |
| Filter persistence | `sessionStorage.setItem('bedboard_unit_filter', unit)` | Persists across navigation within the tab session per DoD requirement |
| API | `GET /api/v1/beds?include_predictions=true` | Queries `mv_bed_board` materialised view including `predicted_discharge_time` |

---

## File Map

| File | Purpose |
|------|---------|
| `src/app/features/beds/components/bed-board/bed-board.component.ts` | Primary grid component |
| `src/app/features/beds/components/bed-board/bed-board.component.html` | Grid template + unit filter toolbar |
| `src/app/features/beds/components/bed-board/bed-board.component.scss` | CSS Grid layout + status colour tokens |
| `src/app/features/beds/components/bed-cell/bed-cell.component.ts` | Individual bed cell atom component |
| `src/app/features/beds/components/bed-cell/bed-cell.component.html` | Cell template with aria-label |
| `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.ts` | Slide-in detail panel |
| `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.html` | Patient info + Assign Bed button |
| `src/app/features/beds/services/bed-board.service.ts` | HTTP service wrapping `GET /api/v1/beds` |
| `src/app/features/beds/services/bed-realtime.service.ts` | SignalR `bed_status_changed` subscriber |
| `src/app/shared/pipes/mask-name.pipe.ts` | Converts full name → initials (J.D.) |
| `src/app/features/beds/models/bed.model.ts` | `BedDto`, `BedStatus` enum, `BedUpdateEvent` |
| `src/app/features/beds/beds.routes.ts` | Lazy route: `/beds` |
| `src/app/features/beds/spec/bed-board.component.spec.ts` | Component unit tests |
| `src/app/features/beds/spec/bed-realtime.service.spec.ts` | SignalR handler tests |
| `src/app/shared/pipes/mask-name.pipe.spec.ts` | Pipe unit tests |

---

## Dependencies and Integration Points

| Dependency | Story | Notes |
|------------|-------|-------|
| Angular scaffold, lazy routes, shared services | US-047 | Feature module skeleton must exist |
| `SignalRService` hub connection | US-048 | `bed_status_changed` event published on this hub |
| `GET /api/v1/beds` endpoint with `mv_bed_board` | US-035 | Must return `predicted_discharge_time` when `?include_predictions=true` |
| Discharge predictions in cell | US-036 | Displayed directly from API response field |
| `AuthService.hasRole()` method | EP-001 | Used for RBAC patient name visibility check |

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| SignalR event schema changes between US-048 and this story | Medium | Define `BedUpdateEvent` interface in TASK-001; coordinate with US-048 implementer |
| CSS Grid layout breaks on 1024px narrow viewports | Low | TASK-004 includes explicit responsive breakpoint test at 1024px list-view fallback |
| RBAC `hasRole()` not yet implemented in `AuthService` | Medium | TASK-003 uses a feature flag / stub if not available; issue blocked dependency |
| `predicted_discharge_time` null for newly admitted patients | Low | TASK-001 renders `—` placeholder; no hard error |

---

## Validation Approach

1. **TASK-001:** Manual render verification — all 5 statuses visible with correct colours in Storybook / dev server
2. **TASK-002:** Inject mock `Subject<BedUpdateEvent>` into `BedRealtimeService`; assert cell `[ngClass]` updates within 1 render cycle
3. **TASK-003:** Test panel open/close animation; assert patient initials vs. full name per role mock
4. **TASK-004:** Cypress component test at 1024px and 2560px; assert `sessionStorage` key persists after route navigation
5. **TASK-005:** Jasmine/Karma unit coverage ≥ 80% for all bed feature files

---

*Tasks generated by plan-development-tasks workflow on 2026-07-17.*
