# US-050 Task Generation Summary

**Story:** US-050 — Render Visual Bed Board with Colour-Coded Status
**Generated:** 2026-07-17
**Workflow:** plan-development-tasks

---

## Generated Artifacts

### Index File

- **File:** `US-050-tasks-index.md`
- **Content:** Task breakdown summary, acceptance criteria coverage matrix, DoD checklist, implementation order, technical decisions, file map, dependencies, risks, validation approach

### Task Files

| Task ID | Title | Layer | Effort | File |
|---------|-------|-------|--------|------|
| TASK-001 | BedBoardComponent — CSS Grid Layout, Colour Map, and Beds API Integration | Frontend — Component | 12 h | `task_001_bed_board_component_grid_colour_api.md` |
| TASK-002 | SignalR `bed_status_changed` Handler — Real-Time Cell State Updates | Frontend — Real-Time | 6 h | `task_002_signalr_bed_status_handler.md` |
| TASK-003 | BedDetailPanelComponent — Slide-In Panel with RBAC Patient Info and Assign Bed Action | Frontend — Component | 8 h | `task_003_bed_detail_panel_rbac.md` |
| TASK-004 | Unit Filter (MatButtonToggle + sessionStorage) and WCAG Accessibility | Frontend — UX/A11y | 8 h | `task_004_unit_filter_skeleton_accessibility.md` |
| TASK-005 | Unit Tests — BedBoard, BedDetailPanel, Filter, and SignalR Handler | Frontend — Testing | 6 h | `task_005_unit_tests_bed_board.md` |

**Total Effort:** 40 hours = 5 story points ✓

---

## Task Breakdown Rationale

### TASK-001: Foundation (12h)
- **Scope:** `BedDto` model, `BedStatus` enum, `BED_STATUS_CLASS` colour map, `BedBoardService` (HTTP), `BedBoardComponent` (CSS Grid, skeleton loaders, signal state), `BedCellComponent` (atom), `MaskNamePipe`, lazy route registration
- **Why First:** Defines the `BedDto` data contract and the `BedBoardComponent.updateBedStatus()` method that TASK-002 depends on; establishes colour token CSS classes consumed by all rendering tests
- **Key Deliverables:** 9 new files, lazy route in `app.routes.ts`, all 5 status colours verified in Storybook

### TASK-002: Real-Time Updates (6h)
- **Scope:** `BedRealtimeService` subscribing to SignalR `bed_status_changed`; integration into `BedBoardComponent.ngOnInit/ngOnDestroy`
- **Why Second (parallel with TASK-003 and TASK-004):** Depends only on TASK-001's `BedDto` interface and `updateBedStatus()` method; can proceed independently of panel and filter work
- **Key Deliverables:** `BedRealtimeService` with start/stop lifecycle; confirmed <1s visual update from SignalR event

### TASK-003: Detail Panel (8h)
- **Scope:** `BedDetailPanelComponent` with slide-in CSS animation, RBAC patient name visibility, risk tier chip, Assign Bed button, Escape key close
- **Why Parallel with TASK-002:** Consumes `BedDto` from TASK-001 only; no SignalR dependency; RBAC check uses `AuthService` (existing EP-001 service)
- **Key Deliverables:** Panel animation 300ms; physician/charge_nurse see full name; `assignBed` EventEmitter output

### TASK-004: Filter + A11y (8h)
- **Scope:** `MatButtonToggleGroup` unit filter toolbar; `computed()` `filteredBeds` signal; `sessionStorage` persistence; WCAG `aria-label` completion; responsive 1024px list-view confirmation
- **Why Parallel with TASK-002/TASK-003:** Depends only on TASK-001 `beds()` signal and `BedDto.unit` field
- **Key Deliverables:** Filter persists across navigation; `aria-label` on every cell passes axe-core; no horizontal overflow at 1024px

### TASK-005: Unit Tests (6h)
- **Scope:** 37 test cases across `MaskNamePipe`, `BedBoardComponent`, `BedRealtimeService`, `BedDetailPanelComponent`; coverage ≥ 80%
- **Why Last:** Written after all implementation is merged to produce realistic fixtures and avoid test-driven scope creep
- **Key Deliverables:** Zero flaky tests; all Angular Signals tests run synchronously without `fakeAsync`

---

## Acceptance Criteria Coverage

| Scenario | Tasks |
|----------|-------|
| SC1: Beds render with correct colour coding (VACANT/OCCUPIED/DIRTY/MAINTENANCE) | TASK-001, TASK-005 |
| SC2: Cell updates within 1s of SignalR `bed_status_changed` | TASK-002, TASK-005 |
| SC3: Click bed cell → side panel with patient info, risk tier, Assign Bed button | TASK-003, TASK-005 |
| SC4: Unit filter shows/hides beds; persists across navigation | TASK-004, TASK-005 |

---

## Implementation Order

```
TASK-001 ──► TASK-002 ──┐
             TASK-003 ──┼──► TASK-005
             TASK-004 ──┘
```

---

## Files Created

| File | Purpose |
|------|---------|
| `US-050-tasks-index.md` | Master index with coverage matrix and implementation order |
| `task_001_bed_board_component_grid_colour_api.md` | BedBoardComponent, BedCellComponent, BedBoardService, MaskNamePipe |
| `task_002_signalr_bed_status_handler.md` | BedRealtimeService + SignalR integration |
| `task_003_bed_detail_panel_rbac.md` | BedDetailPanelComponent + RBAC name visibility |
| `task_004_unit_filter_skeleton_accessibility.md` | Unit filter, sessionStorage, WCAG aria-labels, responsive |
| `task_005_unit_tests_bed_board.md` | 37 Jasmine/Karma unit test cases |
| `TASK_GENERATION_SUMMARY.md` | This file |

---

## Next Steps for Implementation

1. **Review:** Tech Lead and UX Lead review task breakdown; confirm `SignalRService.on/off` API surface matches US-048 contract
2. **Assign:** TASK-001 to Frontend Engineer A (gate); TASK-002, TASK-003, TASK-004 in parallel sprint once TASK-001 merged
3. **TASK-001:** Implement foundation; merge to `feature/US-050-bed-board`
4. **TASK-002 + TASK-003 + TASK-004:** Implement concurrently in parallel branches; each merges to `feature/US-050-bed-board`
5. **TASK-005:** Write unit tests after all implementations merged; run `ng test --code-coverage`; gate ≥ 80%
6. **Code Review:** Peer review all implementations; verify RBAC patient name logic with clinical privacy officer
7. **UX Review:** Run `/analyze-ux` against 1024px and 2560px viewports; zero critical axe-core violations
8. **Deploy:** Merge to `build/development`; smoke test against staging SignalR hub

---

*Task generation completed on 2026-07-17 by plan-development-tasks workflow.*
