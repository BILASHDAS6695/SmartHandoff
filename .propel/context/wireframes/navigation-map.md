# SmartHandoff — Navigation Map

> **Artifact:** navigation-map | **Version:** 1.0 | **Status:** Draft
> **Date:** 2026-07-14 | **Upstream:** figma_spec.md v1.0 | **Workflow:** /generate-wireframe
> **Fidelity:** Hi-Fi

---

## 1. Site Architecture

```
/login
│
├── /dashboard                       [SCR-002] All Staff (role-filtered)
│     │
│     ├── /patients                  [SCR-003] Nurse, Physician
│     │     │
│     │     └── /patients/:id        [SCR-004] All Staff
│     │           │
│     │           ├── /patients/:id/medications   [SCR-005] Pharmacist
│     │           └── /patients/:id/documents     [SCR-006] Physician, Nurse
│     │
│     ├── /beds                      [SCR-007] BedManager
│     │
│     ├── /analytics                 [SCR-009] Manager
│     │
│     └── /admin                     [SCR-011] Admin
│           └── /admin/agents        [SCR-008] Supervisor
│
└── /portal                          [SCR-010] Patient (OTP auth — separate session)
```

---

## 2. Angular Route Guard Matrix

| Route | Component | Guard(s) | Allowed Roles |
|-------|-----------|---------|---------------|
| `/login` | `LoginComponent` | — | Public |
| `/dashboard` | `DashboardComponent` | `AuthGuard`, `RoleGuard` | Nurse, Physician, Pharmacist, BedManager, Manager, Supervisor, Admin |
| `/patients` | `PatientListComponent` | `AuthGuard`, `RoleGuard` | Nurse, Physician |
| `/patients/:id` | `PatientDetailComponent` | `AuthGuard`, `RoleGuard` | Nurse, Physician, Pharmacist, BedManager |
| `/patients/:id/medications` | `MedicationReviewComponent` | `AuthGuard`, `RoleGuard` | Pharmacist |
| `/patients/:id/documents` | `DocumentReviewComponent` | `AuthGuard`, `RoleGuard` | Physician, Nurse |
| `/beds` | `BedBoardComponent` | `AuthGuard`, `RoleGuard` | BedManager |
| `/analytics` | `AnalyticsComponent` | `AuthGuard`, `RoleGuard` | Manager |
| `/admin` | `AdminSettingsComponent` | `AuthGuard`, `RoleGuard` | Admin |
| `/admin/agents` | `AgentMonitorComponent` | `AuthGuard`, `RoleGuard` | Supervisor |
| `/portal` | `PatientPortalComponent` | `PatientAuthGuard` | Patient (OTP session) |

---

## 3. Role-Based Navigation Visibility

| Nav Item | Nurse | Physician | Pharmacist | BedManager | Manager | Supervisor | Admin |
|----------|-------|-----------|------------|------------|---------|------------|-------|
| Dashboard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Patients | ✓ | ✓ | — | — | — | — | — |
| Bed Board | — | — | — | ✓ | — | — | — |
| Analytics | — | — | — | — | ✓ | — | — |
| Agent Monitor | — | — | — | — | — | ✓ | ✓ |
| Admin Settings | — | — | — | — | — | — | ✓ |

---

## 4. User Entry Flows

### 4.1 Staff Entry Flow

```
Browser → /login
  → [SSO button clicked]
  → Redirect to Hospital IdP
  → MFA verification
  → JWT issued (role claims)
  → Redirect to /dashboard
  → Angular RoleGuard reads JWT claims
  → Role-filtered dashboard rendered
  → SignalR connection established
```

### 4.2 Patient Entry Flow

```
Patient receives SMS/email portal link
  → Link contains encrypted token
  → Browser opens /portal?token=...
  → PatientAuthGuard validates token
  → If expired: OTP modal shown
  → OTP sent → patient enters code
  → Session established (60-min timeout)
  → Portal home rendered (language from FHIR preference)
```

---

## 5. Navigation Transitions

| From | Action | To | Method |
|------|--------|----|--------|
| SCR-002 Dashboard | Click patient in risk list | SCR-004 Patient Detail | `router.navigate` |
| SCR-002 Dashboard | Click "View All Tasks" | SCR-003 Patient List | `router.navigate` |
| SCR-003 Patient List | Click "View" on row | SCR-004 Patient Detail | `router.navigate` |
| SCR-004 Patient Detail | Click "Medications" tab | SCR-005 Medication Review | Tab component (lazy load) |
| SCR-004 Patient Detail | Click "Documents" tab | SCR-006 Document Review | Tab component (lazy load) |
| SCR-004 Patient Detail | Click "Review & Approve" | SCR-006 Document Review | `router.navigate` |
| SCR-004 Patient Detail | Click alert "Resolve" | SCR-005 Medication Review | `router.navigate` |
| SCR-007 Bed Board | Click bed tile | In-page slide-out detail panel | Angular CDK Overlay |
| SCR-009 Analytics | Click chart | Filters encounter table (in-page) | Observable filter |
| SCR-011 Admin | Switch section | In-page section swap | Admin sub-nav |
| Any staff screen | Click logo | SCR-002 Dashboard | `router.navigate` |
| Any staff screen | Click notification | SCR-004 Patient Detail | `router.navigate` |
| SCR-010 Portal | Chatbot urgency signal | Emergency full-screen modal | Angular CDK Dialog |

---

## 6. Deep Link Patterns

| Intent | URL Pattern | Example |
|--------|-------------|---------|
| Open patient detail | `/patients/:encounterId` | `/patients/2041` |
| Open patient medications | `/patients/:encounterId/medications` | `/patients/2041/medications` |
| Open patient documents | `/patients/:encounterId/documents` | `/patients/2041/documents` |
| Open specific document for review | `/patients/:encounterId/documents?docId=:docId` | `/patients/2041/documents?docId=8812` |
| Open portal for patient | `/portal?token=:encryptedToken` | `/portal?token=eyJ...` |
| Jump to admin section | `/admin?section=audit-log` | `/admin?section=audit-log` |

---

## 7. Wireframe Inventory

| SCR | Wireframe File | Fidelity | Priority | Persona |
|-----|---------------|----------|----------|---------|
| SCR-001 | [wireframe-SCR-001-login.html](Hi-Fi/wireframe-SCR-001-login.html) | Hi-Fi | Must Have | All |
| SCR-002 | [wireframe-SCR-002-dashboard-home.html](Hi-Fi/wireframe-SCR-002-dashboard-home.html) | Hi-Fi | Must Have | All Staff |
| SCR-003 | [wireframe-SCR-003-patient-list.html](Hi-Fi/wireframe-SCR-003-patient-list.html) | Hi-Fi | Must Have | P-01, P-02 |
| SCR-004 | [wireframe-SCR-004-patient-detail.html](Hi-Fi/wireframe-SCR-004-patient-detail.html) | Hi-Fi | Must Have | All Staff |
| SCR-005 | [wireframe-SCR-005-medication-review.html](Hi-Fi/wireframe-SCR-005-medication-review.html) | Hi-Fi | Must Have | P-03 |
| SCR-006 | [wireframe-SCR-006-document-review.html](Hi-Fi/wireframe-SCR-006-document-review.html) | Hi-Fi | Must Have | P-01, P-02 |
| SCR-007 | [wireframe-SCR-007-bed-board.html](Hi-Fi/wireframe-SCR-007-bed-board.html) | Hi-Fi | Should Have | P-04 |
| SCR-008 | [wireframe-SCR-008-agent-monitor.html](Hi-Fi/wireframe-SCR-008-agent-monitor.html) | Hi-Fi | Should Have | Supervisor |
| SCR-009 | [wireframe-SCR-009-analytics-dashboard.html](Hi-Fi/wireframe-SCR-009-analytics-dashboard.html) | Hi-Fi | Should Have | Manager |
| SCR-010 | [wireframe-SCR-010-patient-portal.html](Hi-Fi/wireframe-SCR-010-patient-portal.html) | Hi-Fi | Must Have | P-05 |
| SCR-011 | [wireframe-SCR-011-admin-settings.html](Hi-Fi/wireframe-SCR-011-admin-settings.html) | Hi-Fi | Must Have | IT Admin |

**Total:** 11 wireframes · 8 Must Have · 3 Should Have

---

## 8. UXR Coverage Validation

| UXR ID | Requirement | Covered By |
|--------|-------------|------------|
| UXR-001 | Responsive 375px–2560px | All screens |
| UXR-002 | WCAG AA Contrast | All screens (design tokens verified) |
| UXR-003 | 44px touch targets | SCR-001, SCR-010 |
| UXR-004 | Skeleton loaders | All screens |
| UXR-005 | Toast notifications | SCR-002, SCR-004, SCR-008, SCR-009 |
| UXR-006 | Critical alert modals | SCR-004, SCR-005, SCR-007 |
| UXR-007 | AI-Assisted badge | SCR-004, SCR-005, SCR-006 |
| UXR-008 | User-friendly errors | SCR-001, SCR-006 |
| UXR-009 | Session timeout warning | SCR-001 (state), all staff screens |
| UXR-010 | Dark mode toggle | Global (design token layer) |
| UXR-011 | Last-updated timestamp | SCR-002, SCR-007, SCR-008 |
| UXR-012 | Onboarding tooltips | SCR-001, SCR-002 |
| UXR-013 | Role-filtered rendering | SCR-002, SCR-003, SCR-011 |
| UXR-014 | PHI masking toggle | SCR-003, SCR-004, SCR-011 |
| UXR-020 | Role-gated navigation | SCR-002 (sidebar) |
| UXR-021 | Notification bell + priority grouping | SCR-002 |
| UXR-022 | ADT feed auto-scroll + pause | SCR-002 |
| UXR-023 | Risk score chips | SCR-002, SCR-003, SCR-004 |
| UXR-024 | Table sort/filter/pagination | SCR-003, SCR-009, SCR-011 |
| UXR-025 | Confirm before irreversible actions | SCR-004, SCR-005, SCR-006, SCR-011 |
| UXR-026 | Keyboard navigation | All staff screens |
| UXR-030 | 6th-grade reading level | SCR-010 |
| UXR-031 | Language selector visible | SCR-010 |
| UXR-032 | Persistent chatbot FAB | SCR-010 |
| UXR-033 | Emergency full-screen card | SCR-010 |
| UXR-034 | Voice-to-text chatbot input | SCR-010 |
| UXR-035 | PDF download | SCR-010 |
| UXR-036 | Thumb-reachable mobile layout | SCR-010 |

**Coverage:** 28/28 UXR requirements addressed across 11 wireframes ✓

---

*Generated by /generate-wireframe workflow | Upstream: figma_spec.md v1.0, designsystem.md v1.0*
