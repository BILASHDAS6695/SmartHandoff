# SmartHandoff — Figma UX Specification

> **Artifact:** figma_spec | **Version:** 1.0 | **Status:** Draft
> **Date:** 2026-07-14 | **Upstream:** SRS v1.0, design.md v1.0 | **Workflow:** /create-figma-spec
> **Designer:** SmartHandoff Project Team

---

## Table of Contents

1. [Overview](#1-overview)
2. [UX Requirements (UXR)](#2-ux-requirements-uxr)
3. [User Personas Reference](#3-user-personas-reference)
4. [Screen Inventory](#4-screen-inventory)
5. [Screen Specifications](#5-screen-specifications)
   - [SCR-001 — Login](#scr-001--login)
   - [SCR-002 — Dashboard Home](#scr-002--dashboard-home)
   - [SCR-003 — Patient List](#scr-003--patient-list)
   - [SCR-004 — Patient Detail](#scr-004--patient-detail)
   - [SCR-005 — Medication Review](#scr-005--medication-review)
   - [SCR-006 — Document Review](#scr-006--document-review)
   - [SCR-007 — Bed Board](#scr-007--bed-board)
   - [SCR-008 — Agent Monitor](#scr-008--agent-monitor)
   - [SCR-009 — Analytics Dashboard](#scr-009--analytics-dashboard)
   - [SCR-010 — Patient Portal](#scr-010--patient-portal)
   - [SCR-011 — Admin Settings](#scr-011--admin-settings)
6. [Navigation Map](#6-navigation-map)
7. [Component Library Summary](#7-component-library-summary)
8. [Interaction Patterns](#8-interaction-patterns)
9. [Accessibility Requirements](#9-accessibility-requirements)
10. [UXR Traceability Matrix](#10-uxr-traceability-matrix)

---

## 1. Overview

SmartHandoff presents two distinct UI surfaces:

| Surface | Audience | Primary Device | Auth Method |
|---------|----------|----------------|-------------|
| **Staff Dashboard** (Angular 17 PWA) | Nurse, Physician, Pharmacist, Bed Manager, Supervisor, Admin | Desktop (primary), Tablet | SSO + MFA (OIDC) |
| **Patient Portal** (Mobile-first PWA) | Discharged Patients | Mobile Browser | OTP / Magic Link |

Both surfaces share the SmartHandoff design system tokens (see `designsystem.md`). All screens are responsive: staff dashboard targets 1024px–2560px; patient portal targets ≥375px.

---

## 2. UX Requirements (UXR)

### 2.1 Global UX Requirements

| ID | Requirement | Source | Priority |
|----|-------------|--------|----------|
| UXR-001 | All screens shall be responsive across 375px–2560px viewport widths | UI-001, UI-002, NFR-033 | Must Have |
| UXR-002 | All interactive elements shall meet WCAG 2.1 AA contrast ratio (≥4.5:1 text, ≥3:1 UI components) | UI-004, NFR-034 | Must Have |
| UXR-003 | Touch targets shall be a minimum of 44×44px on all touch-capable surfaces | UI-002 | Must Have |
| UXR-004 | All async content panels shall display skeleton loaders during loading states | UI-007 | Must Have |
| UXR-005 | Toast notifications shall appear top-right, auto-dismiss in 5 seconds, and support screen readers via `aria-live="polite"` | UI-005 | Must Have |
| UXR-006 | Critical alerts (drug interactions, boarding alerts) shall use modal interrupts with explicit acknowledgement | UI-005, BR-005 | Must Have |
| UXR-007 | All AI-generated content panels shall display a persistent "AI-Assisted — Review Required" badge until clinician approval | FR-025, BR-011 | Must Have |
| UXR-008 | Error messages shall be user-friendly with a recovery action link; no technical stack traces exposed | UI-008 | Must Have |
| UXR-009 | Session timeout warning shall appear at T-5 minutes with a "Stay Logged In" option | BR-013, SEC-009 | Must Have |
| UXR-010 | Dark mode shall be applied system-preference-aware with a manual toggle available in the user menu | UI-006 | Should Have |
| UXR-011 | Real-time data panels shall show a "Last updated" timestamp and a manual refresh option | FR-012, NFR-006 | Should Have |
| UXR-012 | New user training to proficiency shall be achievable within 2 hours via contextual tooltips and onboarding walkthrough | NFR-030 | Should Have |
| UXR-013 | All dashboard data shall be role-filtered at render time — no hidden elements that leak data to unauthorised roles | FR-074, SEC-002 | Must Have |
| UXR-014 | PHI fields (MRN, name, DOB) shall be maskable with a toggle for public-facing or shared-screen scenarios | BR-012, HIPAA | Should Have |

### 2.2 Staff Dashboard UX Requirements

| ID | Requirement | Source | Priority |
|----|-------------|--------|----------|
| UXR-020 | Role-specific navigation items shall be visible only to the assigned role — no greyed-out items for unauthorised screens | FR-074 | Must Have |
| UXR-021 | The global notification bell shall show unread count badge and group alerts by priority (critical / warning / info) | FR-012, UI-005 | Must Have |
| UXR-022 | The ADT event feed shall auto-scroll to newest events with a "Pause" option for reading older entries | FR-070 | Should Have |
| UXR-023 | Patient risk scores shall be rendered with colour-coded severity chips: green (<0.3), amber (0.3–0.7), red (>0.7) | FR-071 | Must Have |
| UXR-024 | All data tables shall support column sorting, filtering, and pagination (25/50/100 rows per page) | FR-070–075 | Should Have |
| UXR-025 | Confirmation dialogs shall be required before irreversible actions (approve & sign, cancel ADT) | BR-001, BR-011 | Must Have |
| UXR-026 | Keyboard navigation shall be fully functional across all staff screens (Tab, Shift+Tab, Enter, Escape, Arrow keys) | NFR-034 | Must Have |

### 2.3 Patient Portal UX Requirements

| ID | Requirement | Source | Priority |
|----|-------------|--------|----------|
| UXR-030 | Portal shall render discharge instructions at ≤6th-grade reading level with visual section headers | FR-021 | Must Have |
| UXR-031 | Portal shall display content in the patient's preferred language with a language selector always visible | FR-022, BR-004 | Must Have |
| UXR-032 | The chatbot widget shall be persistently accessible (fixed bottom-right) on all portal screens | FR-060 | Must Have |
| UXR-033 | Urgency signals in chatbot (chest pain, bleeding, etc.) shall immediately surface emergency contact card in full-screen modal | FR-063 | Must Have |
| UXR-034 | Portal shall support voice-to-text input via the Web Speech API (microphone icon in chatbot input) | FR-064 | Could Have |
| UXR-035 | Discharge instructions shall be downloadable as a PDF from the portal | FR-075 | Should Have |
| UXR-036 | All portal actions shall be completable on a single hand with thumb reach on a standard 375px mobile screen | UI-002 | Should Have |

---

## 3. User Personas Reference

| ID | Persona | Role | Key Goals | Primary Screen |
|----|---------|------|-----------|----------------|
| P-01 | Nurse Nancy | Floor Nurse | Complete handoff tasks fast; view patient status | SCR-002, SCR-004 |
| P-02 | Dr. David | Attending Physician | Approve discharges; review AI summaries | SCR-004, SCR-006 |
| P-03 | Pharmacist Phil | Clinical Pharmacist | Reconcile medications; resolve drug interaction alerts | SCR-005 |
| P-04 | Coordinator Carol | Bed Manager | Monitor bed map; manage patient flow; resolve ED boarding alerts | SCR-007 |
| P-05 | Patient Pat | Discharged Patient | Understand instructions; ask chatbot questions | SCR-010 |

---

## 4. Screen Inventory

| SCR | Screen Name | Route | Primary Persona | Priority | UC Refs |
|-----|-------------|-------|-----------------|----------|---------|
| SCR-001 | Login | `/login` | All | Must Have | UC-010, UC-011 |
| SCR-002 | Dashboard Home | `/dashboard` | All Staff | Must Have | UC-010, UC-018, UC-019, UC-020 |
| SCR-003 | Patient List | `/patients` | P-01, P-02 | Must Have | UC-010 |
| SCR-004 | Patient Detail | `/patients/:id` | All Staff | Must Have | UC-001–005, UC-009, UC-012, UC-013 |
| SCR-005 | Medication Review | `/patients/:id/medications` | P-03 | Must Have | UC-005, UC-012 |
| SCR-006 | Document Review | `/patients/:id/documents` | P-02, P-01 | Must Have | UC-004, UC-009 |
| SCR-007 | Bed Board | `/beds` | P-04 | Should Have | UC-006, UC-018 |
| SCR-008 | Agent Monitor | `/admin/agents` | Supervisor | Should Have | UC-020 |
| SCR-009 | Analytics Dashboard | `/analytics` | Manager | Should Have | UC-019 |
| SCR-010 | Patient Portal | `/portal` | P-05 | Must Have | UC-008, UC-011, UC-014 |
| SCR-011 | Admin Settings | `/admin` | IT Admin | Must Have | UC-015, UC-016 |

---

## 5. Screen Specifications

---

### SCR-001 — Login

**Route:** `/login`
**Primary Persona:** All users
**UC Refs:** UC-010, UC-011
**Priority:** Must Have

#### Layout

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│           [SmartHandoff Logo]                        │
│         AI-Powered Care Transitions                  │
│                                                      │
│   ┌──────────────────────────────────────────────┐   │
│   │          Staff Login                         │   │
│   │                                              │   │
│   │  [Hospital SSO Button — "Sign in with SSO"]  │   │
│   │                                              │   │
│   │  ──────────── or ────────────                │   │
│   │                                              │   │
│   │  Are you a patient?                          │   │
│   │  [Patient Portal Link]                       │   │
│   └──────────────────────────────────────────────┘   │
│                                                      │
│   Version 1.0 | HIPAA Compliant | © SmartHandoff     │
└──────────────────────────────────────────────────────┘
```

#### States

| State | Description | Trigger |
|-------|-------------|---------|
| Default | Login card visible; SSO button active | Page load |
| Loading | SSO button shows spinner; disabled | SSO redirect in progress |
| Error | Error banner: "Login failed. Contact IT support." | SSO/IdP error |
| Patient Auth | OTP input shown in patient modal | Patient portal link clicked |
| OTP Sent | "Code sent to your number" confirmation | OTP triggered |
| MFA Challenge | MFA verification screen (delegated to IdP) | Post-SSO |

#### Interaction Flow

1. Staff clicks "Sign in with SSO" → redirected to IdP login + MFA
2. JWT received → role extracted → redirected to `/dashboard` (role-filtered)
3. Patient clicks "Patient Portal" → email/phone input modal → OTP sent → portal unlocked

#### UXR Coverage

UXR-001, UXR-002, UXR-003, UXR-008, UXR-009

---

### SCR-002 — Dashboard Home

**Route:** `/dashboard`
**Primary Persona:** P-01 (Nurse), P-02 (Physician), P-03 (Pharmacist), P-04 (Bed Manager)
**UC Refs:** UC-010, UC-018, UC-019, UC-020
**Priority:** Must Have

#### Layout (Nurse / Physician view — 1440px)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Logo] SmartHandoff     [Search patients...]  [🔔 3]  [Avatar ▾]        │
├──────────────────────────────────────────────────────────────────────────┤
│  Nav: Dashboard | Patients | [Bed Board*] | [Analytics*] | [Admin*]     │
│  (* = role-gated)                                                        │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────┐  ┌────────────────────────────────────┐ │
│  │  MY PENDING TASKS (7)       │  │  LIVE ADT EVENT FEED               │ │
│  │  ─────────────────────────  │  │  ─────────────────────────────── │ │
│  │  ● Discharge checklist      │  │  A03 — Smith, J — Unit 4W — 14:32 │ │
│  │    [Patient: Smith, J]      │  │  A01 — Patel, R — Unit 3N — 14:29 │ │
│  │    Due: 15:00   [URGENT]   │  │  A02 — Nguyen, L — 4W→ICU — 14:25 │ │
│  │  ● Review handoff checklist │  │                         [Pause ⏸] │ │
│  │    [Patient: Patel, R]      │  └────────────────────────────────────┘ │
│  │    Due: 16:30               │                                         │
│  │  ● Medication approval      │  ┌────────────────────────────────────┐ │
│  │    [Patient: Nguyen, L]     │  │  ACTIVE PATIENTS — RISK OVERVIEW   │ │
│  │    Due: ASAP  [CRITICAL]   │  │  ─────────────────────────────── │ │
│  │  [View All Tasks →]         │  │  ● Smith, J    ████ 0.82 [HIGH]   │ │
│  └─────────────────────────────┘  │  ● Patel, R    ██░░ 0.45 [MED]    │ │
│                                   │  ● Nguyen, L   █░░░ 0.18 [LOW]    │ │
│  ┌─────────────────────────────┐  │  [View All Patients →]            │ │
│  │  AGENT STATUS               │  └────────────────────────────────────┘ │
│  │  ─────────────────────────  │                                         │
│  │  Transition  ✓ Active       │                                         │
│  │  Documentation ✓ Active     │                                         │
│  │  Medication  ⚠ 2 alerts     │                                         │
│  │  Bed Mgmt    ✓ Active       │                                         │
│  │  Follow-up   ✓ Active       │                                         │
│  │  Patient Comms ✓ Active     │                                         │
│  └─────────────────────────────┘                                         │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description | Trigger |
|-------|-------------|---------|
| Default (loaded) | All panels populated via SignalR | Role-based JWT validated |
| Skeleton loading | All panels show skeleton placeholders | Initial page load |
| High-priority alert | Interrupt modal for critical drug interaction / ED boarding | Agent fires alert |
| Session warning | Bottom banner: "Session expires in 5 minutes" | T-5 min idle |
| No tasks | "Great work! No pending tasks." empty state illustration | All tasks cleared |
| Agent failure | Red agent status chip; "View Error" link | Agent health check fails |

#### Role-Filtered Panels

| Role | Task List | ADT Feed | Risk Overview | Agent Status |
|------|-----------|----------|---------------|--------------|
| Nurse | ✓ (clinical tasks) | ✓ | ✓ | ✓ (read-only) |
| Physician | ✓ (approval queue) | ✓ | ✓ | ✗ |
| Pharmacist | ✓ (med reconciliation) | ✓ | ✗ | ✗ |
| Bed Manager | ✗ | ✓ | ✗ | ✗ |

#### UXR Coverage

UXR-001, UXR-004, UXR-005, UXR-006, UXR-011, UXR-013, UXR-020, UXR-021, UXR-022, UXR-023

---

### SCR-003 — Patient List

**Route:** `/patients`
**Primary Persona:** P-01 (Nurse), P-02 (Physician)
**UC Refs:** UC-010
**Priority:** Must Have

#### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]                                                             │
├──────────────────────────────────────────────────────────────────────────┤
│  Patients   [🔍 Search by name or MRN...]   [Filter ▾]  [Unit ▾]       │
│                                                                          │
│  ┌──────┬──────────────┬────────┬──────────────┬──────────┬───────────┐  │
│  │ MRN  │ Name         │ Unit   │ Status       │ Risk     │ Actions   │  │
│  ├──────┼──────────────┼────────┼──────────────┼──────────┼───────────┤  │
│  │ ●●●● │ Smith, John  │ 4W     │ Admitted     │ ████0.82 │ [View]    │  │
│  │ ●●●● │ Patel, Rita  │ 3N     │ Discharging  │ ██░░0.45 │ [View]    │  │
│  │ ●●●● │ Nguyen, Lee  │ ICU    │ Transferred  │ █░░░0.18 │ [View]    │  │
│  └──────┴──────────────┴────────┴──────────────┴──────────┴───────────┘  │
│                                                                          │
│  Showing 1–25 of 142   [< Prev] [1] [2] [3] [Next >]                   │
│  Rows per page: [25 ▾]                                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default | Paginated table with risk score chips |
| Skeleton | Table rows show skeleton placeholders on load |
| Search active | Table filters to matching patients in real time |
| Empty search | "No patients match your search." with clear filter link |
| MRN masked | ●●●● shown; "Reveal" icon for authorised roles only |

#### UXR Coverage

UXR-013, UXR-014, UXR-023, UXR-024, UXR-026

---

### SCR-004 — Patient Detail

**Route:** `/patients/:id`
**Primary Persona:** All Staff (P-01, P-02, P-03, P-04)
**UC Refs:** UC-001–005, UC-009, UC-012, UC-013
**Priority:** Must Have

#### Layout (1440px — Physician view)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]    ← Back to Patients                                       │
├──────────────────────────────────────────────────────────────────────────┤
│  Smith, John  MRN: ●●●●●●   DOB: ●●/●●/●●●●   Unit: 4-West  Bed: 4W-12 │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  Attending: Dr. Chen  |  Admitted: 2026-07-10  |  Risk: ████ 0.82 HIGH  │
├──────────────────────────────────────────────────────────────────────────┤
│  Tabs: [Overview] [Medications] [Documents] [Tasks] [Timeline]           │
│                                                                          │
│  ── OVERVIEW TAB ──                                                      │
│  ┌───────────────────────────┐  ┌────────────────────────────────────┐   │
│  │ AGENT TASK STATUS         │  │ PENDING APPROVALS (1)              │   │
│  │ ─────────────────────── │  │ ─────────────────────────────────  │   │
│  │ ✓ Transition Coord.      │  │ [AI-Assisted — Review Required]    │   │
│  │ ✓ Documentation          │  │ Discharge Summary — Draft          │   │
│  │ ⚠ Medication Recon.      │  │ Generated 14:32 · 30 sec          │   │
│  │ ✓ Bed Management         │  │ [Review & Approve →]               │   │
│  │ ● Follow-up (pending)    │  └────────────────────────────────────┘   │
│  │ ✓ Patient Comms          │                                           │
│  └───────────────────────────┘  ┌────────────────────────────────────┐   │
│                                 │ READMISSION RISK                   │   │
│  ┌───────────────────────────┐  │ ─────────────────────────────────  │   │
│  │ ACTIVE ALERTS (2)         │  │ Score: 0.82                        │   │
│  │ ─────────────────────── │  │ ████████████████████ HIGH RISK     │   │
│  │ 🔴 Drug interaction:      │  │                                    │   │
│  │    Warfarin + Aspirin     │  │ Contributing factors:              │   │
│  │    [Resolve →]            │  │ • Prior admission <30 days         │   │
│  │ 🟡 Chronic med missing:   │  │ • ≥3 medications changed           │   │
│  │    Metformin not on DC Rx │  │ • HF diagnosis                     │   │
│  │    [Review →]             │  │                                    │   │
│  └───────────────────────────┘  │ [View Care Plan →]                 │   │
│                                 └────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default / Overview | All panels populated; task statuses shown |
| Documents tab | Links to SCR-006 document review inline pane |
| Medications tab | Links to SCR-005 medication review inline pane |
| Tasks tab | Full list of agent tasks for this encounter |
| Timeline tab | Chronological encounter event log |
| Alert modal | Full-screen interrupt for critical drug interaction alert |
| Approval pending | Pulsing blue border on pending approval card |
| AI badge visible | Orange "AI-Assisted — Review Required" badge on all AI content |

#### UXR Coverage

UXR-004, UXR-005, UXR-006, UXR-007, UXR-011, UXR-014, UXR-023, UXR-025

---

### SCR-005 — Medication Review

**Route:** `/patients/:id/medications`
**Primary Persona:** P-03 (Pharmacist Phil)
**UC Refs:** UC-005, UC-012
**Priority:** Must Have

#### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]   Patient: Smith, J   ←  Back to Patient Detail            │
├──────────────────────────────────────────────────────────────────────────┤
│  MEDICATION RECONCILIATION                    [AI-Assisted — Review Required] │
│                                                                          │
│  ┌────────────────────┬───────────────────┬──────────────────────────┐   │
│  │ PRE-ADMISSION      │ INPATIENT         │ DISCHARGE Rx             │   │
│  │ (FHIR Statement)   │ (FHIR Admin.)     │ (FHIR Request)          │   │
│  ├────────────────────┼───────────────────┼──────────────────────────┤   │
│  │ Warfarin 5mg QD    │ Warfarin 5mg QD   │ Warfarin 5mg QD ✓       │   │
│  │ Aspirin 81mg QD    │ Aspirin 81mg QD   │ Aspirin 81mg QD ⚠INTER  │   │
│  │ Metformin 500mg BD │ Metformin 500mg BD│ ── MISSING ──  ⚠CHRONIC │   │
│  │ Lisinopril 10mg QD │ Lisinopril 10mg QD│ Lisinopril 10mg QD ✓    │   │
│  └────────────────────┴───────────────────┴──────────────────────────┘   │
│                                                                          │
│  ACTIVE ALERTS                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ 🔴 MAJOR INTERACTION: Warfarin + Aspirin                          │   │
│  │ Severity: Major | Risk: Increased bleeding                        │   │
│  │ Rationale: Pharmacodynamic synergy; INR may rise significantly    │   │
│  │ [Contact Prescriber] [Accept with Plan] [View Evidence]          │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ 🟡 CHRONIC MED MISSING: Metformin 500mg BD                       │   │
│  │ Not found on Discharge Rx. Patient has Type 2 Diabetes.          │   │
│  │ [Flag for Physician] [Mark Intentional Omission]                 │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  [Generate Patient Medication Summary]   [Complete Reconciliation ✓]    │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default | Three-column medication comparison with alert panel |
| Skeleton | Column placeholders during FHIR data fetch |
| Critical alert interrupt | Full modal requiring acknowledgement for major interactions |
| Resolution recorded | Alert card shows green resolved badge with pharmacist note |
| Complete | "Reconciliation complete" banner; discharge unblocked |
| Escalation (24h SLA) | Red countdown timer; supervisor notified |

#### UXR Coverage

UXR-004, UXR-006, UXR-007, UXR-011, UXR-025

---

### SCR-006 — Document Review

**Route:** `/patients/:id/documents`
**Primary Persona:** P-02 (Dr. David), P-01 (Nurse Nancy)
**UC Refs:** UC-004, UC-009
**Priority:** Must Have

#### Layout (Dual-Pane Review UI)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]   Document Review — Smith, John — Discharge Summary        │
│ [AI-Assisted — Review Required]                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────┬─────────────────────────────────────┐  │
│  │  AI DRAFT (read-only)        │  EDITABLE VERSION                   │  │
│  │  Generated: 14:32            │  Last saved: 14:38 (auto-save)      │  │
│  │  ────────────────────────── │  ───────────────────────────────── │  │
│  │  DISCHARGE SUMMARY           │  DISCHARGE SUMMARY                  │  │
│  │                              │                                     │  │
│  │  Patient: John Smith         │  Patient: John Smith                │  │
│  │  Admission: 2026-07-10       │  Admission: 2026-07-10              │  │
│  │  Discharge: 2026-07-14       │  Discharge: 2026-07-14              │  │
│  │                              │                                     │  │
│  │  Primary Diagnosis:          │  Primary Diagnosis:                 │  │
│  │  Congestive Heart Failure    │  Congestive Heart Failure           │  │
│  │  (I50.9)                     │  (I50.9) [EDITED ✎]                │  │
│  │                              │                                     │  │
│  │  Hospital Course:            │  Hospital Course:                   │  │
│  │  Patient presented with...   │  Patient presented with...  [+Add] │  │
│  │  [HIGHLIGHTED DIFF ██████]   │                                     │  │
│  └──────────────────────────────┴─────────────────────────────────────┘  │
│                                                                          │
│  Change log: [2 edits by Dr. Chen — 14:37]                              │
│                                                                          │
│  [← Reject & Return]  [Save Draft]  [Approve & Sign ✓]                  │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| AI draft pending | Dual-pane shown; right pane is blank awaiting physician edits |
| Editing | Right pane editable; auto-save every 30 seconds; change tracking active |
| Completeness failure | Red banner listing missing required fields; approve blocked |
| Confirm approval | Modal: "By approving you are digitally signing this document. Continue?" |
| Approved | Green banner; document locked; audit entry created; proceed to patient portal |
| Rejected | Red banner; rejection reason input; returned to documentation agent queue |
| Vertex AI fallback | Yellow banner: "AI generation timed out — template used. Review carefully." |

#### UXR Coverage

UXR-004, UXR-007, UXR-008, UXR-025

---

### SCR-007 — Bed Board

**Route:** `/beds`
**Primary Persona:** P-04 (Coordinator Carol)
**UC Refs:** UC-006, UC-018
**Priority:** Should Have

#### Layout (Dual Monitor — 2560px)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]   BED BOARD — LIVE VIEW   Last updated: 14:39:01  [↻]     │
├──────────────────────────────────────────────────────────────────────────┤
│  Filter: [All Units ▾]  [All Status ▾]   Legend: ■Clean ■Dirty ■Occup ■Block │
│                                                                          │
│  UNIT 4-WEST                                                            │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐            │
│  │4W-01 │4W-02 │4W-03 │4W-04 │4W-05 │4W-06 │4W-07 │4W-08 │            │
│  │OCCUP │DIRTY │ CLEAN│OCCUP │OCCUP │BLOCK │OCCUP │ CLEAN│            │
│  │Smith │ HK ─ │ AVAIL│Patel │Jones │Maint.│Lee   │ AVAIL│            │
│  │0.82🔴│      │      │0.45🟡│0.20🟢│      │0.18🟢│      │            │
│  │DC:16h│      │      │DC:32h│DC:8h │      │DC:24h│      │            │
│  └──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘            │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │  🚨 ED BOARDING ALERT — Patient pending for 2h 15m           │      │
│  │  Patient: Garcia, M  |  Unit: Pending  |  Acuity: High       │      │
│  │  Recommended beds: [4W-03 ✓] [3N-07] [3N-12]               │      │
│  │  [Assign 4W-03 →]   [View All Available]   [Dismiss ✗]       │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                                                          │
│  PREDICTED DISCHARGES (next 4 hours)                                    │
│  Jones (4W-05) — 16:00 (±2h)  |  Patel (4W-04) — 18:30 (±2h)          │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default | Floor-plan grid with real-time bed status tiles |
| ED Boarding Alert | Orange alert banner with recommended bed list |
| Bed assignment modal | Confirm dialog before assigning bed to patient |
| Housekeeping notification | Dirty bed tile shows HK notification timestamp |
| Discharge prediction | Countdown timer shown on occupied beds with predictions |

#### UXR Coverage

UXR-001, UXR-004, UXR-006, UXR-011, UXR-025

---

### SCR-008 — Agent Monitor

**Route:** `/admin/agents`
**Primary Persona:** IT Supervisor
**UC Refs:** UC-020
**Priority:** Should Have

#### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]   AGENT HEALTH MONITOR   Last updated: 14:39:05  [↻]      │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┬─────────┬──────────┬───────────┬────────┬───────┐  │
│  │ Agent            │ Status  │ Tasks/hr │ Success % │ Avg ms │ Queue │  │
│  ├──────────────────┼─────────┼──────────┼───────────┼────────┼───────┤  │
│  │ Transition Coord.│ ✓ LIVE  │   42     │   99.8%   │  320   │  0    │  │
│  │ Documentation    │ ✓ LIVE  │   18     │   98.1%   │ 28,400 │  2    │  │
│  │ Medication Recon.│ ⚠ WARN  │   12     │   94.5%   │  450   │  5    │  │
│  │ Bed Management   │ ✓ LIVE  │   38     │  100.0%   │  180   │  0    │  │
│  │ Follow-up Care   │ ✓ LIVE  │   22     │   97.3%   │  520   │  1    │  │
│  │ Patient Comms    │ ✓ LIVE  │   60     │   99.2%   │  810   │  0    │  │
│  └──────────────────┴─────────┴──────────┴───────────┴────────┴───────┘  │
│                                                                          │
│  FAILED TASKS (3)                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Task #8821 — Medication Recon — Encounter #2041                  │    │
│  │ Error: FHIR timeout after 30s | Attempt: 3/3                    │    │
│  │ [View Details]  [Retry]  [Escalate to On-Call]                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  INFRASTRUCTURE                                                          │
│  Pub/Sub lag: 0.2s  |  Cloud SQL latency: 12ms  |  Cloud Run: 3/4 pods │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| All healthy | All agents green; failed tasks count = 0 |
| Agent warning | Yellow chip; elevated error rate; investigation link |
| Agent down | Red chip; retry/escalate options; infra alert |
| Task retry modal | Confirm retry for failed task with attempts remaining |

#### UXR Coverage

UXR-004, UXR-011, UXR-025

---

### SCR-009 — Analytics Dashboard

**Route:** `/analytics`
**Primary Persona:** Hospital Manager
**UC Refs:** UC-019
**Priority:** Should Have

#### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]   ANALYTICS   Date Range: [Last 30 days ▾]  Unit: [All ▾] │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────┬──────────────────┬────────────────┬────────────────┐ │
│  │ AVG DISCHARGE  │ 30-DAY READMIT   │ MED RECON      │ BED UTIL.      │ │
│  │ TIME           │ RATE             │ COMPLETION     │                │ │
│  │   4.2 hrs      │    8.3%          │   96.4%        │   87%          │ │
│  │  ↓ -0.8 (30d)  │  ↓ -1.1% (30d)  │ ↑ +2.1% (30d) │  ↑ +3% (30d)  │ │
│  └────────────────┴──────────────────┴────────────────┴────────────────┘ │
│                                                                          │
│  ┌──────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │ DISCHARGE VOLUME (trend)     │  │ READMISSION RISK DISTRIBUTION   │  │
│  │  [Line chart — 30 days]      │  │  [Doughnut: Low/Med/High]       │  │
│  │  ─────────────────────────  │  │  Low: 64%  Med: 28%  High: 8%  │  │
│  └──────────────────────────────┘  └─────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ TOP 10 HIGH-RISK ENCOUNTERS (last 7 days)                         │   │
│  │ [Sortable table — patient, risk, unit, discharge date]            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  [Export CSV]  [Export PDF]                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default | KPI tiles + charts loaded for default date range |
| Skeleton | Tile and chart placeholders on load |
| Drill-down | Clicking a chart filters the encounter table below |
| Export loading | "Generating report…" overlay on export button click |

#### UXR Coverage

UXR-004, UXR-011, UXR-024, UXR-025

---

### SCR-010 — Patient Portal

**Route:** `/portal`
**Primary Persona:** P-05 (Patient Pat)
**UC Refs:** UC-008, UC-011, UC-014
**Priority:** Must Have

#### Layout (375px Mobile)

```
┌─────────────────────────────┐
│ [SmartHandoff Logo]    [EN▾]│
│ Welcome, John               │
│ Discharged: July 14, 2026   │
├─────────────────────────────┤
│  ┌───────────────────────┐  │
│  │ 💊 MY MEDICATIONS     │  │
│  │ 5 medications         │  │
│  │ [View Details →]      │  │
│  └───────────────────────┘  │
│  ┌───────────────────────┐  │
│  │ 📋 MY DISCHARGE       │  │
│  │    INSTRUCTIONS       │  │
│  │ Activity · Diet ·     │  │
│  │ Warning Signs         │  │
│  │ [View Instructions →] │  │
│  └───────────────────────┘  │
│  ┌───────────────────────┐  │
│  │ 📅 FOLLOW-UP          │  │
│  │ Dr. Chen — July 21    │  │
│  │ 09:00 AM | Cardiology │  │
│  │ [Add to Calendar]     │  │
│  └───────────────────────┘  │
│  ┌───────────────────────┐  │
│  │ ⚠️ WARNING SIGNS      │  │
│  │ Go to ER immediately: │  │
│  │ • Chest pain          │  │
│  │ • Difficulty breathing│  │
│  │ • Sudden weight gain  │  │
│  └───────────────────────┘  │
│                             │
│  [📄 Download PDF]          │
│                             │
│       ┌──────────────────┐  │
│       │  💬 Ask a        │  │
│       │  Question        │  │
│       └──────────────────┘  │
└─────────────────────────────┘
```

#### Chatbot Widget (Expanded State — 375px)

```
┌─────────────────────────────┐
│ SmartHandoff Assistant  [✕] │
├─────────────────────────────┤
│                             │
│  ┌─────────────────────┐   │
│  │ How often do I take │   │
│  │ my Warfarin?        │   │
│  └─────────────────────┘   │
│                             │
│  ┌──────────────────────┐  │
│  │ Take Warfarin 5mg    │  │
│  │ every day, at the   │  │
│  │ same time.          │  │
│  │                     │  │
│  │ [🩺 Talk to Care    │  │
│  │  Team]              │  │
│  └──────────────────────┘  │
│                             │
│  [🎤] [Ask a question...]  [→] │
└─────────────────────────────┘
```

#### Emergency Alert State (Full-Screen)

```
┌─────────────────────────────┐
│ 🚨 EMERGENCY                │
│ ────────────────────────── │
│ You may need emergency help.│
│                             │
│ CALL 911 NOW                │
│ [📞 911]                    │
│                             │
│ Or call your hospital:      │
│ [📞 (555) 000-0000]         │
│                             │
│ Your care team has been     │
│ notified.                   │
│                             │
│ [Return to Portal]          │
└─────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default | Card-based summary of medications, instructions, appointments |
| Language selected | All content re-rendered in selected language |
| Chatbot closed | Floating action button bottom-right |
| Chatbot open | Chat panel slides up; 60% screen height |
| Emergency detected | Full-screen emergency card with 911 + hospital number |
| PDF download | Loading spinner on PDF button; download triggered |

#### UXR Coverage

UXR-001, UXR-002, UXR-003, UXR-030, UXR-031, UXR-032, UXR-033, UXR-034, UXR-035, UXR-036

---

### SCR-011 — Admin Settings

**Route:** `/admin`
**Primary Persona:** IT Admin
**UC Refs:** UC-015, UC-016
**Priority:** Must Have

#### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Global Nav]   ADMIN SETTINGS                                            │
├──────────────────────────────────────────────────────────────────────────┤
│  Sidebar: [User Management ▸] [Audit Log ▸] [System Config ▸]           │
├──────────────────────────────────────────────────────────────────────────┤
│  USER MANAGEMENT                                         [+ Add User]    │
│                                                                          │
│  ┌─────────┬────────────────┬───────────────┬──────────┬─────────────┐   │
│  │ Name    │ Email          │ Role          │ Status   │ Actions     │   │
│  ├─────────┼────────────────┼───────────────┼──────────┼─────────────┤   │
│  │ J. Smith│ j.smith@hosp. │ Nurse         │ Active   │ [Edit][Dis] │   │
│  │ D. Chen │ d.chen@hosp.  │ Physician     │ Active   │ [Edit][Dis] │   │
│  │ P. Phil │ p.phil@hosp.  │ Pharmacist    │ Active   │ [Edit][Dis] │   │
│  └─────────┴────────────────┴───────────────┴──────────┴─────────────┘   │
│                                                                          │
│  AUDIT LOG                                             [Export CSV]      │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Filter: [Date range ▾] [User ▾] [Event Type ▾]  [Apply]        │    │
│  ├─────────────────────────────────────────────────────────────────┤    │
│  │ 2026-07-14 14:32 | j.smith | READ | Patient #2041 (MRN masked) │    │
│  │ 2026-07-14 14:30 | d.chen  | SIGN | Document #8812             │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

#### States

| State | Description |
|-------|-------------|
| Default | User table; audit log filter panel |
| Add user modal | Role picker; SSO provisioning confirmation |
| Disable user confirmation | "This will immediately revoke all active sessions." modal |
| Audit log filtered | Table narrows to matching events; PHI masked |
| Export in progress | "Generating export…" spinner |

#### UXR Coverage

UXR-013, UXR-014, UXR-024, UXR-025

---

## 6. Navigation Map

```
/login
  │
  ├── /dashboard                (All Staff — role-filtered)
  │     ├── /patients           (Nurse, Physician)
  │     │     └── /patients/:id (All Staff)
  │     │           ├── /patients/:id/medications  (Pharmacist)
  │     │           └── /patients/:id/documents    (Physician, Nurse)
  │     ├── /beds               (Bed Manager)
  │     ├── /analytics          (Manager)
  │     └── /admin              (IT Admin)
  │           ├── /admin/agents (Supervisor)
  │           └── /admin (User Mgmt + Audit Log)
  │
  └── /portal                   (Patient — OTP auth)
```

**Angular Route Guards:**

| Route | Guard | Allowed Roles |
|-------|-------|---------------|
| `/dashboard` | `AuthGuard`, `RoleGuard` | All staff roles |
| `/patients` | `RoleGuard` | Nurse, Physician |
| `/patients/:id/medications` | `RoleGuard` | Pharmacist |
| `/patients/:id/documents` | `RoleGuard` | Physician, Nurse |
| `/beds` | `RoleGuard` | BedManager |
| `/analytics` | `RoleGuard` | Manager |
| `/admin` | `RoleGuard` | Admin |
| `/admin/agents` | `RoleGuard` | Supervisor |
| `/portal` | `PatientAuthGuard` | Patient (OTP) |

---

## 7. Component Library Summary

| Component | Used On | States |
|-----------|---------|--------|
| `RiskScoreChip` | SCR-002, SCR-003, SCR-004 | low/medium/high (green/amber/red) |
| `AgentStatusBadge` | SCR-002, SCR-004, SCR-008 | active/warning/failed |
| `AiBadge` | SCR-004, SCR-005, SCR-006 | review-required / approved |
| `AlertBanner` | SCR-005, SCR-006, SCR-007 | critical (red) / warning (amber) / info (blue) |
| `PatientCard` | SCR-003, SCR-004 | default / masked |
| `SkeletonLoader` | All screens | rows / cards / charts |
| `ToastNotification` | All screens | critical / warning / info / success |
| `ConfirmModal` | SCR-004, SCR-005, SCR-006, SCR-011 | destructive / informational |
| `DualPaneEditor` | SCR-006 | editing / locked / approved / rejected |
| `BedTile` | SCR-007 | clean / dirty / occupied / blocked |
| `ChatWidget` | SCR-010 | closed / open / typing / emergency |
| `SessionTimeoutBanner` | All staff screens | warning (T-5 min) |
| `KpiCard` | SCR-009 | positive-trend / negative-trend / neutral |
| `RoleFilteredNav` | All staff screens | per-role visibility |

---

## 8. Interaction Patterns

### 8.1 Real-Time Updates

All staff dashboard panels subscribe to SignalR hub channels. When a new ADT event or agent status change arrives:

1. Panel data is updated in-place (no full page reload)
2. New or changed items briefly highlight with a 500ms pulse animation
3. Notification bell badge count increments
4. Critical alerts surface as modal interrupts requiring acknowledgement

### 8.2 AI-Assisted Content Flow

1. AI draft appears with orange `AiBadge` — "AI-Assisted — Review Required"
2. Clinician opens document via pending approval card or task notification
3. Dual-pane editor shown; right pane is editable; left pane is AI draft (read-only)
4. On "Approve & Sign": confirmation modal → document locked → badge replaced with green "Approved" stamp
5. On "Reject": rejection reason required → document returned to documentation queue

### 8.3 Alert Escalation Pattern

| Alert Type | Initial Delivery | Escalation (T+15 min) | Escalation (T+30 min) |
|------------|------------------|----------------------|----------------------|
| Drug interaction | Pharmacist toast + dashboard badge | Pharmacist modal interrupt | Backup pharmacist notified |
| ED Boarding | Bed Manager banner | Bed Manager modal interrupt | ED Charge Nurse alerted |
| Unacknowledged task | Assignee toast | Assignee modal | Supervisor notified |

### 8.4 Chatbot Urgency Detection

1. Patient message analysed in real time for urgency signals (chest pain, can't breathe, bleeding)
2. On detection: chatbot response paused; full-screen emergency card shown immediately
3. Care team alert created in background; patient shown hospital emergency number
4. "Connect with Care Team" button initiates escalation workflow

---

## 9. Accessibility Requirements

| Requirement | Implementation |
|-------------|----------------|
| Screen reader support | All interactive elements have `aria-label` or visible label; `aria-live` regions for real-time updates |
| Keyboard navigation | Full tab order; modals trap focus; Escape closes overlays |
| Colour not sole indicator | Risk levels use chip + icon + text (not colour only) |
| Colour contrast | Minimum 4.5:1 for text; 3:1 for UI components — verified with design tokens |
| Focus visible | Custom focus ring: 2px solid `#0066CC`, 2px offset |
| Reduced motion | All animations respect `prefers-reduced-motion: reduce` |
| Font scaling | UI functional at 200% browser zoom |
| Form labels | All inputs have associated `<label>` elements |
| Error identification | Errors identified in text, not colour alone; `role="alert"` on dynamic errors |

---

## 10. UXR Traceability Matrix

| UXR ID | Requirement Summary | SCR(s) | FR/BR/NFR Refs |
|--------|---------------------|--------|----------------|
| UXR-001 | Responsive 375px–2560px | All | UI-001, UI-002, NFR-033 |
| UXR-002 | WCAG AA contrast | All | UI-004, NFR-034 |
| UXR-003 | 44×44px touch targets | All | UI-002 |
| UXR-004 | Skeleton loaders | All | UI-007 |
| UXR-005 | Toast notifications | SCR-002, 004, 008, 009 | UI-005 |
| UXR-006 | Modal interrupts for critical alerts | SCR-004, 005, 007 | BR-005 |
| UXR-007 | AI-Assisted badge | SCR-004, 005, 006 | FR-025, BR-011 |
| UXR-008 | User-friendly errors | All | UI-008 |
| UXR-009 | Session timeout warning | All staff | BR-013, SEC-009 |
| UXR-010 | Dark mode toggle | All | UI-006 |
| UXR-011 | Last-updated timestamp | SCR-002, 007, 008 | NFR-006 |
| UXR-012 | Onboarding tooltips | SCR-001, 002 | NFR-030 |
| UXR-013 | Role-filtered rendering | SCR-002, 003, 011 | FR-074, SEC-002 |
| UXR-014 | PHI masking toggle | SCR-003, 004, 011 | BR-012 |
| UXR-020 | Role-gated navigation | All staff | FR-074 |
| UXR-021 | Notification bell with priority grouping | All staff | UI-005 |
| UXR-022 | ADT feed auto-scroll with pause | SCR-002 | FR-070 |
| UXR-023 | Risk score colour chips | SCR-002, 003, 004 | FR-071 |
| UXR-024 | Table sort/filter/pagination | SCR-003, 009, 011 | FR-070–075 |
| UXR-025 | Confirm dialog for irreversible actions | SCR-004, 005, 006, 011 | BR-001, BR-011 |
| UXR-026 | Full keyboard navigation | All staff | NFR-034 |
| UXR-030 | 6th-grade reading level | SCR-010 | FR-021 |
| UXR-031 | Language selector always visible | SCR-010 | FR-022, BR-004 |
| UXR-032 | Persistent chatbot FAB | SCR-010 | FR-060 |
| UXR-033 | Urgency → full-screen emergency card | SCR-010 | FR-063 |
| UXR-034 | Voice-to-text chatbot input | SCR-010 | FR-064 |
| UXR-035 | PDF download | SCR-010 | FR-075 |
| UXR-036 | Thumb-reachable mobile layout | SCR-010 | UI-002 |

---

*Generated by /create-figma-spec workflow | Upstream: docs/spec.md v1.0*
