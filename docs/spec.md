# SmartHandoff — Software Requirements Specification (SRS)

> **Version:** 1.0 | **Status:** Draft | **Date:** 2026-07-13  
> **Source:** BRD v1.0 (July 10, 2026) | **Prepared by:** SmartHandoff Project Team

---

## Table of Contents

1. [Document Overview](#1-document-overview)
2. [System Context & Scope](#2-system-context--scope)
3. [Stakeholders & Personas](#3-stakeholders--personas)
4. [Functional Requirements](#4-functional-requirements)
5. [Use Cases](#5-use-cases)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Business Rules](#7-business-rules)
8. [Data Requirements](#8-data-requirements)
9. [Integration Requirements](#9-integration-requirements)
10. [Security & Compliance Requirements](#10-security--compliance-requirements)
11. [UI / UX Requirements](#11-ui--ux-requirements)
12. [Acceptance Criteria](#12-acceptance-criteria)
13. [Assumptions & Constraints](#13-assumptions--constraints)
14. [Requirements Traceability Matrix](#14-requirements-traceability-matrix)
15. [Glossary](#15-glossary)

---

## 1. Document Overview

### 1.1 Purpose

This Software Requirements Specification (SRS) translates the SmartHandoff Business Requirements Document (BRD v1.0) into structured, testable functional requirements (FR-XXX) and use cases (UC-XXX) ready for downstream design, development, and testing workflows.

### 1.2 System Summary

**SmartHandoff** is an AI-powered care transition orchestrator that automates and coordinates healthcare Admission, Discharge, and Transfer (ADT) workflows through six specialised LangChain AI agents deployed on Google Cloud Platform (GCP). The system consumes real-time HL7 ADT messages, fetches patient context via FHIR R4, and drives staff dashboards and patient portals built in Angular 17.

### 1.3 Document Conventions

| Prefix | Meaning |
|--------|---------|
| `FR-XXX` | Functional Requirement |
| `NFR-XXX` | Non-Functional Requirement |
| `UC-XXX` | Use Case |
| `BR-XXX` | Business Rule |
| `SEC-XXX` | Security Requirement |
| `UI-XXX` | UI/UX Requirement |
| `BO-XX` | Business Objective (from BRD) |

Priority levels: **Must Have** · **Should Have** · **Could Have** · **Won't Have (Phase 1)**

---

## 2. System Context & Scope

### 2.1 System Boundary

```
┌────────────────────────────────────────────────────────────────────────┐
│                         SMARTHANDOFF SYSTEM                            │
│                                                                        │
│  ┌──────────────┐   ┌─────────────────────────────────────────────┐   │
│  │  Angular 17  │   │               FastAPI Backend                │   │
│  │  PWA / Portal│◄──►  REST + WebSocket (SignalR)                  │   │
│  └──────────────┘   │                                             │   │
│                     │  ┌─────────────────────────────────────┐   │   │
│                     │  │        AI Agent Orchestrator         │   │   │
│                     │  │  (LangChain + Vertex AI / Gemini)    │   │   │
│                     │  │                                     │   │   │
│                     │  │  ┌──────────┐  ┌─────────────────┐ │   │   │
│                     │  │  │Transition│  │  Documentation  │ │   │   │
│                     │  │  │Coordinator  │     Agent       │ │   │   │
│                     │  │  └──────────┘  └─────────────────┘ │   │   │
│                     │  │  ┌──────────┐  ┌─────────────────┐ │   │   │
│                     │  │  │Medication│  │  Bed Management │ │   │   │
│                     │  │  │  Recon.  │  │     Agent       │ │   │   │
│                     │  │  └──────────┘  └─────────────────┘ │   │   │
│                     │  │  ┌──────────┐  ┌─────────────────┐ │   │   │
│                     │  │  │Follow-up │  │    Patient      │ │   │   │
│                     │  │  │  Care    │  │  Communication  │ │   │   │
│                     │  │  └──────────┘  └─────────────────┘ │   │   │
│                     │  └─────────────────────────────────────┘   │   │
│                     │                                             │   │
│                     │  ┌───────────┐   ┌────────────────────┐   │   │
│                     │  │ Cloud SQL  │   │  GCP Pub/Sub       │   │   │
│                     │  │(PostgreSQL)│   │  (Event Bus)       │   │   │
│                     │  └───────────┘   └────────────────────┘   │   │
│                     └─────────────────────────────────────────────┘   │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
  ┌───────────┐        ┌──────────────┐       ┌─────────────┐
  │ EHR System│        │  Identity    │       │Twilio/Send  │
  │ HL7 ADT   │        │  Provider    │       │Grid (Notif) │
  │ FHIR R4   │        │ OIDC/OAuth2  │       │             │
  └───────────┘        └──────────────┘       └─────────────┘
```

### 2.2 In-Scope (Phase 1 / MVP)

- Real-time HL7 ADT event ingestion and processing (A01, A02, A03, A04, A08, A11, A12, A13)
- Six AI agent subsystems orchestrated by the Transition Coordinator Agent
- Angular 17 PWA: care team dashboard + patient portal
- FHIR R4 read-only EHR integration
- GCP infrastructure: Cloud Run, Cloud SQL (PostgreSQL), Pub/Sub, Vertex AI
- HIPAA-compliant audit logging, RBAC, AES-256 encryption

### 2.3 Out-of-Scope (Phase 1)

| Item | Deferred To |
|------|-------------|
| EHR write-back integration | Phase 2 |
| Voice-enabled interfaces | Phase 2 |
| IoT bed sensors | Phase 3 |
| Insurance pre-authorization | Phase 3 |
| Multi-hospital federation | Phase 3 |

---

## 3. Stakeholders & Personas

### 3.1 Stakeholder Map

| Stakeholder | Type | Primary Needs |
|-------------|------|---------------|
| Hospital Administration | Sponsor | ROI, compliance, reputation |
| Chief Medical Officer | Decision Maker | Patient safety, clinical outcomes |
| Chief Nursing Officer | Decision Maker | Staff efficiency, workflow fit |
| IT Director | Technical Owner | Integration, security, maintainability |
| Nursing Staff | Primary User | Ease of use, time savings |
| Attending Physicians | Primary User | Clinical accuracy, alert precision |
| Clinical Pharmacists | Primary User | Medication safety, interaction alerts |
| Bed Management Team | Primary User | Real-time visibility, flow control |
| Patients / Caregivers | Beneficiary | Clear communication, safe care |
| Compliance Officer | Reviewer | HIPAA, HITECH, Joint Commission |

### 3.2 User Personas

| ID | Persona | Role | Key Goals | Primary Device |
|----|---------|------|-----------|----------------|
| P-01 | Nurse Nancy | Floor Nurse | Complete handoff tasks fast, view patient status | Desktop, Tablet |
| P-02 | Dr. David | Attending Physician | Approve discharges, review AI summaries | Desktop, Mobile |
| P-03 | Pharmacist Phil | Clinical Pharmacist | Reconcile medications, resolve conflicts | Desktop |
| P-04 | Coordinator Carol | Bed Manager | Monitor bed map, manage patient flow | Desktop (dual monitor) |
| P-05 | Patient Pat | Discharged Patient | Understand instructions, ask questions | Mobile |

---

## 4. Functional Requirements

### 4.1 ADT Event Processing

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-001 | System shall receive and process HL7 ADT messages via MLLP/TCP in real-time with end-to-end latency ≤5 seconds | Must Have | BRD §6.1 | All Staff |
| FR-002 | System shall support ADT event types: A01 (Admit), A02 (Transfer), A03 (Discharge), A04 (Register), A08 (Update), A11 (Cancel Admit), A12 (Cancel Transfer), A13 (Cancel Discharge) | Must Have | BRD §6.1, §10.3 | All |
| FR-003 | System shall parse HL7 v2.x message segments (MSH, EVN, PID, PV1, PV2) and map them to the internal `ADTEvent` domain model | Must Have | BRD §6.1 | System |
| FR-004 | System shall trigger the appropriate AI agent workflow within 2 seconds of ADT event persistence | Must Have | BRD §6.1 | System |
| FR-005 | System shall maintain a complete, immutable audit trail of all ADT events including source system, receipt timestamp, and processing outcome | Must Have | BRD §6.1, BR-023 | Compliance Officer |
| FR-006 | System shall handle ADT cancellation events (A11, A12, A13) by halting in-progress agent workflows and updating encounter status accordingly | Must Have | BRD §10.3 | System |

### 4.2 Transition Coordinator Agent

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-010 | Transition Coordinator Agent shall orchestrate task assignment across all five specialised agents upon receiving an ADT trigger | Must Have | BRD §6.2 | System |
| FR-011 | Agent shall track completion status of each sub-task and escalate any task delayed beyond configured SLA thresholds | Must Have | BRD §6.2 | Nurse Nancy, Supervisor |
| FR-012 | Agent shall publish real-time status updates to connected dashboard clients via SignalR WebSocket with latency ≤1 second | Must Have | BRD §6.2, NFR-006 | All Staff |
| FR-013 | Agent shall generate context-aware handoff checklists tailored to patient diagnosis, care unit, and transition type | Should Have | BRD §6.2 | Nurse Nancy |
| FR-014 | Agent shall expose a task status API endpoint (`GET /api/v1/encounters/{id}/tasks`) for dashboard polling and audit | Must Have | BRD §6.2 | All Staff |

### 4.3 Documentation Agent

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-020 | Documentation Agent shall auto-generate a draft discharge summary from encounter data, diagnosis codes, and clinical notes within 30 seconds of an A03 event | Must Have | BRD §6.3 | Dr. David |
| FR-021 | Agent shall generate patient-friendly discharge instructions at a ≤6th-grade reading level, structured by medications, activity, diet, and follow-up | Must Have | BRD §6.3 | Patient Pat |
| FR-022 | Agent shall support document generation in a minimum of 5 languages: English, Spanish, French, Mandarin, Portuguese | Should Have | BRD §6.3 | Patient Pat |
| FR-023 | Agent shall perform a completeness check against a configurable required-fields checklist before marking documentation as ready for review | Must Have | BRD §6.3, BR-001 | Compliance Officer |
| FR-024 | All AI-generated documents shall be presented in a dual-pane review interface allowing inline editing with change tracking; final approval requires a licensed clinician action | Must Have | BRD §6.3, BR-011 | Dr. David, Nurse Nancy |
| FR-025 | Agent shall label all AI-generated content with a persistent "AI-Assisted — Review Required" watermark until clinician approval is recorded | Must Have | BR-011 | All Clinicians |

### 4.4 Medication Reconciliation Agent

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-030 | Medication Reconciliation Agent shall retrieve and compare pre-admission medications (FHIR MedicationStatement), inpatient medications (MedicationAdministration), and discharge medications (MedicationRequest) | Must Have | BRD §6.4 | Pharmacist Phil |
| FR-031 | Agent shall detect and flag drug-drug interactions using an integrated drug interaction database with ≥99% sensitivity for major interactions | Must Have | BRD §6.4 | Pharmacist Phil |
| FR-032 | Agent shall identify and flag therapeutic duplicates across all medication lists | Must Have | BRD §6.4 | Pharmacist Phil |
| FR-033 | Agent shall highlight chronic maintenance medications absent from the discharge prescription list and prompt prescriber action | Should Have | BRD §6.4 | Dr. David |
| FR-034 | Agent shall generate a patient-readable medication change summary listing added, stopped, and changed medications with plain-language rationale | Must Have | BRD §6.4 | Patient Pat |
| FR-035 | Agent shall generate real-time priority alerts to pharmacists for cases where: (a) ≥1 major drug interaction is detected, (b) ≥3 medications changed, or (c) high-risk drug classes (anticoagulants, insulin, opioids) are involved | Must Have | BRD §6.4, BR-005 | Pharmacist Phil |
| FR-036 | Agent shall complete initial reconciliation within 24 hours of A01 admission trigger | Must Have | BR-002 | Pharmacist Phil |

### 4.5 Bed Management Agent

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-040 | Bed Management Agent shall predict patient discharge time using a Scikit-learn regression model, with predictions accurate to within ±2 hours | Should Have | BRD §6.5 | Coordinator Carol |
| FR-041 | Agent shall maintain and serve a real-time bed availability map reflecting bed status (clean/dirty/occupied/blocked), unit, room, and bed type | Must Have | BRD §6.5 | Coordinator Carol |
| FR-042 | Agent shall score and recommend optimal bed assignments for incoming patients based on acuity level, required care type, isolation requirements, and gender | Should Have | BRD §6.5 | Coordinator Carol |
| FR-043 | Agent shall generate an ED boarding alert when a patient has waited >2 hours for inpatient bed assignment, escalating to the bed manager and charge nurse | Must Have | BRD §6.5, BO-05 | Coordinator Carol |
| FR-044 | Agent shall trigger automated bed turnover notification to environmental services upon an A03 (Discharge) event | Should Have | BRD §6.5 | Coordinator Carol |

### 4.6 Follow-up Care Agent

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-050 | Follow-up Care Agent shall schedule follow-up appointments via FHIR Appointment resource before discharge is finalised, completing within 30 minutes of A03 trigger | Should Have | BRD §6.6 | Discharge Planner |
| FR-051 | Agent shall send automated medication reminder SMS/email messages to patients at prescribed intervals using Twilio/SendGrid | Should Have | BRD §6.6 | Patient Pat |
| FR-052 | Agent shall calculate a 30-day readmission risk score (0.0–1.0) using a Scikit-learn classification model at discharge; scores ≥0.7 trigger the high-risk care pathway | Must Have | BRD §6.6, BO-02, BR-003 | Care Manager |
| FR-053 | Agent shall escalate patient-reported post-discharge concerns to the assigned care team within 15 minutes if flagged as clinical concerns | Must Have | BRD §6.6 | Nurse Nancy |
| FR-054 | Agent shall schedule a 48-hour post-discharge automated check-in for all patients with readmission risk score ≥0.5 | Should Have | BR-003 | Care Manager |

### 4.7 Patient Communication Agent

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-060 | Patient Communication Agent shall provide a 24/7 AI chatbot interface in the patient portal, accessible without app installation via mobile browser | Must Have | BRD §6.7 | Patient Pat |
| FR-061 | Chatbot shall answer questions scoped to the patient's own discharge instructions, medications, follow-up appointments, and warning signs | Must Have | BRD §6.7 | Patient Pat |
| FR-062 | Chatbot shall respond to patient queries within 3 seconds for standard questions; complex clinical queries shall be escalated to the on-call care team within 2 minutes | Must Have | BRD §6.7 | Patient Pat |
| FR-063 | Chatbot shall detect urgency signals (e.g., "chest pain", "can't breathe", "bleeding") and immediately display emergency contact information and initiate a care team alert | Must Have | Patient Safety | Patient Pat |
| FR-064 | Agent shall support voice-to-text input via Web Speech API for accessibility | Could Have | BRD §6.7 | Patient Pat |
| FR-065 | All chatbot conversation transcripts shall be stored against the patient encounter record for care team review | Must Have | HIPAA | Care Team |

### 4.8 Dashboard & Reporting

| ID | Requirement | Priority | BRD Ref | Persona |
|----|-------------|----------|---------|---------|
| FR-070 | Dashboard shall display a live ADT event feed showing event type, patient MRN (masked), unit, and timestamp, auto-refreshed via SignalR | Must Have | BRD §6.8 | All Staff |
| FR-071 | Dashboard shall display each patient's readmission risk score with colour-coded severity (green <0.3, amber 0.3–0.7, red >0.7) | Must Have | BRD §6.8 | Nurse Nancy |
| FR-072 | Dashboard shall display per-agent task status (pending/in-progress/complete/failed) with elapsed time for all active encounters | Must Have | BRD §6.8 | Supervisor |
| FR-073 | System shall provide an analytics module with configurable KPI dashboards: discharge time, readmission rate, medication error rate, bed utilisation, patient satisfaction | Should Have | BRD §6.8 | Manager |
| FR-074 | Dashboard views shall be role-filtered: nurses see clinical tasks; pharmacists see medication queues; bed managers see bed board; physicians see approval queues | Must Have | BRD §6.8, SEC-002 | All Staff |
| FR-075 | System shall support data export of analytics reports in CSV and PDF formats | Should Have | BRD §6.8 | Manager |

---

## 5. Use Cases

### UC-001: Process Patient Admission (ADT A01)

| Field | Value |
|-------|-------|
| **ID** | UC-001 |
| **Title** | Process Patient Admission |
| **Actors** | EHR System (Primary), Transition Coordinator Agent, Documentation Agent, Medication Reconciliation Agent, Bed Management Agent |
| **Trigger** | HL7 ADT^A01 message received on MLLP listener |
| **Preconditions** | MLLP listener active; FHIR endpoint accessible; patient MRN resolvable |
| **BRD Refs** | FR-001, FR-003, FR-004, FR-010, FR-030, FR-036, FR-041 |

**Main Flow:**

1. MLLP listener receives `ADT^A01` and ACKs within 200ms
2. Parser extracts PID, PV1, DG1 segments; creates `ADTEvent` record; publishes to GCP Pub/Sub
3. Transition Coordinator Agent subscribes, creates `Encounter` record, initiates workflow
4. Coordinator dispatches parallel tasks: FHIR patient data fetch, bed assignment, initial med reconciliation
5. Bed Management Agent assigns optimal bed and updates bed board
6. Medication Reconciliation Agent fetches pre-admission medications; begins 24-hour reconciliation window
7. Dashboard notifies all connected staff via SignalR within 1 second

**Alternate Flows:**

- **A1 — Patient not found in FHIR:** Agent logs warning, creates partial encounter, alerts admissions clerk
- **A2 — No bed available:** Agent places patient on waiting list, triggers capacity alert

**Postconditions:** Encounter created; bed assigned or waitlisted; medication reconciliation initiated; staff notified

---

### UC-002: Process Patient Transfer (ADT A02)

| Field | Value |
|-------|-------|
| **ID** | UC-002 |
| **Title** | Process Patient Unit Transfer |
| **Actors** | EHR System, Transition Coordinator Agent, Documentation Agent, Bed Management Agent |
| **Trigger** | HL7 ADT^A02 message received |
| **Preconditions** | Active encounter exists; destination unit has available bed |
| **BRD Refs** | FR-001, FR-002, FR-010, FR-013, FR-041 |

**Main Flow:**

1. MLLP listener receives `ADT^A02`; parser extracts source and destination unit from PV1
2. System updates `Encounter.Unit`; publishes to Pub/Sub
3. Coordinator Agent generates transfer-specific handoff checklist for receiving unit nurse
4. Bed Management Agent marks source bed dirty/available; marks destination bed occupied
5. Documentation Agent creates transfer note summarising active problems, pending orders, and care plan
6. Dashboard notifies both sending and receiving unit staff via SignalR

**Postconditions:** Encounter unit updated; handoff checklist delivered; bed board current

---

### UC-003: Process Patient Discharge (ADT A03)

| Field | Value |
|-------|-------|
| **ID** | UC-003 |
| **Title** | Process Patient Discharge |
| **Actors** | EHR System, Transition Coordinator Agent, Documentation Agent, Medication Reconciliation Agent, Follow-up Care Agent, Patient Communication Agent, Bed Management Agent |
| **Trigger** | HL7 ADT^A03 message received |
| **Preconditions** | Active encounter exists; attending physician has approved discharge order |
| **BRD Refs** | FR-001, FR-002, FR-010, FR-020, FR-021, FR-030, FR-050, FR-052, FR-060 |

**Main Flow:**

1. MLLP listener receives `ADT^A03`; Coordinator Agent orchestrates full discharge workflow
2. Documentation Agent generates draft discharge summary (≤30 seconds) and patient instructions
3. Medication Reconciliation Agent produces final medication change summary
4. Follow-up Care Agent calculates readmission risk score and schedules follow-up appointment
5. All documents surfaced in physician approval queue on dashboard
6. Physician reviews, edits if needed, approves — triggering document finalisation
7. Patient portal populated with finalised instructions; patient notified via SMS/email
8. Patient Communication Agent activates chatbot for 30-day post-discharge window
9. Bed Management Agent marks bed dirty; notifies environmental services
10. Encounter status set to `DISCHARGED`; audit record closed

**Alternate Flows:**

- **A1 — Documentation incomplete:** Completeness check fails; discharge blocked; nurse alerted
- **A2 — High readmission risk (≥0.7):** Follow-up mandatory within 7 days; care manager alerted

**Postconditions:** Encounter closed; documents signed; patient portal active; follow-up scheduled; bed available

---

### UC-004: Generate AI Discharge Summary

| Field | Value |
|-------|-------|
| **ID** | UC-004 |
| **Title** | Generate and Review AI Discharge Summary |
| **Actors** | Documentation Agent, Attending Physician (P-02), Nurse (P-01) |
| **Trigger** | ADT A03 event or manual physician request |
| **Preconditions** | Encounter active; FHIR data accessible; Vertex AI available |
| **BRD Refs** | FR-020, FR-023, FR-024, FR-025, BR-001, BR-011 |

**Main Flow:**

1. Documentation Agent retrieves encounter data, ICD-10 codes, and clinical notes from FHIR
2. Agent constructs structured LLM prompt; Vertex AI generates draft discharge summary within 30 seconds
3. Agent runs completeness validation against required-fields checklist
4. Draft presented in dual-pane review UI with "AI-Assisted — Review Required" label
5. Physician edits inline; change tracking records all modifications with authorship
6. Physician clicks "Approve & Sign" — document finalised; clinician identity and timestamp recorded

**Alternate Flow:** Vertex AI timeout → system falls back to template-based summary; physician alerted

**Postconditions:** Signed discharge summary on record; HIPAA audit entry created

---

### UC-005: Medication Reconciliation

| Field | Value |
|-------|-------|
| **ID** | UC-005 |
| **Title** | Perform Medication Reconciliation |
| **Actors** | Medication Reconciliation Agent, Pharmacist Phil (P-03), Physician (P-02) |
| **Trigger** | ADT A01 (admission) or ADT A03 (discharge) event |
| **Preconditions** | FHIR MedicationStatement accessible; drug interaction database online |
| **BRD Refs** | FR-030, FR-031, FR-032, FR-033, FR-034, FR-035, FR-036, BR-002, BR-005 |

**Main Flow:**

1. Agent fetches three medication lists from FHIR: pre-admission, inpatient, discharge prescription
2. Agent compares lists and categorises changes: continued / new / stopped / dose-changed
3. Agent queries drug interaction database for all active medication combinations
4. Agent flags: drug-drug interactions by severity, duplicates, missing chronic medications
5. Pharmacist receives priority-ranked reconciliation queue on dashboard
6. Pharmacist reviews, resolves conflicts, documents rationale
7. Agent generates patient-readable medication change summary
8. High-risk cases trigger immediate pharmacist alert (FR-035)

**Alternate Flows:**

- **A1 — Not completed in 24 hours:** Escalated to charge pharmacist (BR-002)
- **A2 — Critical interaction:** Immediate alert to pharmacist AND prescribing physician; discharge held

**Postconditions:** Reconciliation record complete; patient medication summary generated; alerts resolved

---

### UC-006: Real-Time Bed Board Management

| Field | Value |
|-------|-------|
| **ID** | UC-006 |
| **Title** | Monitor and Manage Bed Availability |
| **Actors** | Bed Management Agent, Coordinator Carol (P-04) |
| **Trigger** | ADT event (A01/A02/A03) or periodic refresh (every 60 seconds) |
| **Preconditions** | Bed inventory seeded; unit configurations complete |
| **BRD Refs** | FR-040, FR-041, FR-042, FR-043, FR-044 |

**Main Flow:**

1. Bed Board screen displays visual floor-plan grid with colour-coded bed status
2. Agent updates bed status in real time on each ADT event via SignalR
3. Agent ML model generates predicted discharge times for all active patients
4. On incoming admission (A01), Agent scores available beds and presents ranked recommendation
5. Coordinator assigns bed; Agent updates board; sends unit assignment notification
6. On discharge (A03), Agent marks bed dirty; sends housekeeping notification

**Alternate Flow:** ED wait >2 hours → Agent fires ED Boarding Alert to bed manager and ED charge nurse

**Postconditions:** Bed board current within 60 seconds; assignments recorded; alerts dispatched

---

### UC-007: Post-Discharge Follow-up Scheduling

| Field | Value |
|-------|-------|
| **ID** | UC-007 |
| **Title** | Schedule Post-Discharge Follow-up Care |
| **Actors** | Follow-up Care Agent, Discharge Planner, Patient Pat (P-05) |
| **Trigger** | ADT A03 (Discharge) event |
| **Preconditions** | Risk score calculated; FHIR Appointment endpoint available |
| **BRD Refs** | FR-050, FR-051, FR-052, FR-054, BR-003 |

**Main Flow:**

1. Agent calculates readmission risk score at A03 event
2. Risk ≥0.7: follow-up within 7 days; care manager alerted; high-risk pathway activated
3. Risk 0.3–0.7: standard follow-up within 14 days
4. Agent books FHIR Appointment; sends confirmation to patient via SMS and email
5. Medication reminder messages scheduled per discharge prescription
6. Risk ≥0.5: 48-hour post-discharge check-in automated message queued

**Postconditions:** Appointment booked; reminders scheduled; care manager alerted if high-risk

---

### UC-008: Patient Chatbot Interaction

| Field | Value |
|-------|-------|
| **ID** | UC-008 |
| **Title** | Patient Engages Post-Discharge Chatbot |
| **Actors** | Patient Communication Agent, Patient Pat (P-05), Care Team (escalation) |
| **Trigger** | Patient opens chatbot in patient portal |
| **Preconditions** | Patient authenticated; discharge complete; encounter record accessible |
| **BRD Refs** | FR-060, FR-061, FR-062, FR-063, FR-064, FR-065 |

**Main Flow:**

1. Patient authenticates on mobile browser via OTP/magic link
2. Patient types or dictates question about discharge instructions
3. Agent retrieves patient's finalised discharge documents
4. Vertex AI LLM generates contextual answer within 3 seconds
5. Response displayed with "Connect with Care Team" option
6. Conversation transcript stored against encounter record

**Alternate Flows:**

- **A1 — Urgency signal detected:** Chatbot immediately displays 911 / emergency hotline; creates high-priority care team alert
- **A2 — Clinical escalation:** Routes to on-call nurse within 2 minutes; patient shown wait time

**Postconditions:** Question answered or escalated; transcript stored; alerts dispatched if urgent

---

### UC-009: Clinician Reviews AI-Generated Content

| Field | Value |
|-------|-------|
| **ID** | UC-009 |
| **Title** | Clinician Reviews and Approves AI-Generated Document |
| **Actors** | Documentation Agent, Physician (P-02), Nurse (P-01) |
| **Trigger** | AI-generated document enters pending-review state |
| **Preconditions** | Document generated; clinician authenticated with review role |
| **BRD Refs** | FR-024, FR-025, BR-001, BR-011 |

**Main Flow:**

1. Clinician sees notification badge on dashboard for pending approvals
2. Opens review queue; document shown with "AI-Assisted" label
3. Reviews in dual-pane editor (AI draft left, editable right)
4. Makes inline edits; change tracking records author and timestamp
5. Clicks "Approve & Sign" — document finalised; HIPAA audit entry created
6. If rejected: returned with rejection reason; agent regenerates or flags for manual completion

**Postconditions:** Document finalised or returned; audit trail complete

---

### UC-010: Role-Based Dashboard Access

| Field | Value |
|-------|-------|
| **ID** | UC-010 |
| **Title** | Staff Member Accesses Role-Filtered Dashboard |
| **Actors** | All Staff Personas (P-01 to P-04) |
| **Trigger** | Staff member logs in via SSO |
| **Preconditions** | User account provisioned; role assigned in IdP |
| **BRD Refs** | FR-070, FR-071, FR-072, FR-074, SEC-001, SEC-002 |

**Main Flow:**

1. User navigates to SmartHandoff URL; redirected to SSO login with MFA
2. JWT issued with role claims; Angular loads role-specific dashboard
3. Nurse: patient task list, risk scores, handoff checklists
4. Pharmacist: medication reconciliation queue, interaction alerts
5. Bed Manager: bed board, ED boarding alerts, discharge predictions
6. Physician: approval queues, patient summaries, risk flags
7. Real-time updates stream via SignalR for all panels

**Postconditions:** User sees only role-appropriate data; 30-minute idle timeout enforced

---

### UC-011: Patient Portal Access

| Field | Value |
|-------|-------|
| **ID** | UC-011 |
| **Title** | Patient Accesses Discharge Instructions via Portal |
| **Actors** | Patient Pat (P-05) |
| **Trigger** | Patient receives SMS/email portal link post-discharge |
| **Preconditions** | Discharge complete; portal link generated; patient contact info on file |
| **BRD Refs** | FR-021, FR-022, FR-060, FR-065, PRV-001, PRV-004 |

**Main Flow:**

1. Patient receives personalised portal link via SMS/email
2. Patient authenticates via OTP or magic link
3. Portal displays discharge instructions in patient's preferred language
4. Patient can view medications, follow-up appointments, and warning signs
5. Patient can download/print instructions as PDF
6. Chatbot widget available for questions

**Postconditions:** Patient has access to instructions; chatbot active; access logged for HIPAA

---

### UC-012: Pharmacist Drug Interaction Alert Response

| Field | Value |
|-------|-------|
| **ID** | UC-012 |
| **Title** | Pharmacist Responds to Drug Interaction Alert |
| **Actors** | Medication Reconciliation Agent, Pharmacist Phil (P-03), Physician (P-02) |
| **Trigger** | Agent detects major drug-drug interaction |
| **Preconditions** | Medication reconciliation in progress; pharmacist reachable |
| **BRD Refs** | FR-031, FR-035, BR-005 |

**Main Flow:**

1. Agent detects major interaction; generates high-priority alert with severity, drug pair, and clinical rationale
2. Alert pushed to pharmacist dashboard in real time
3. Pharmacist reviews and contacts prescribing physician (tracked in system)
4. Resolution recorded: medication changed / interaction accepted with monitoring plan / escalated
5. Alert closed with resolution note; audit entry created

**Alternate Flow:** Pharmacist unavailable >15 minutes → alert escalated to backup pharmacist (BR-014)

**Postconditions:** Interaction resolved; audit complete; discharge unblocked or held

---

### UC-013: Readmission Risk Escalation

| Field | Value |
|-------|-------|
| **ID** | UC-013 |
| **Title** | High-Risk Patient Escalation Workflow |
| **Actors** | Follow-up Care Agent, Care Manager, Nurse (P-01) |
| **Trigger** | Readmission risk score ≥0.7 at discharge |
| **Preconditions** | ML model loaded; A03 event processed |
| **BRD Refs** | FR-052, FR-053, FR-054, BR-003 |

**Main Flow:**

1. Agent calculates risk score ≥0.7; patient flagged HIGH RISK (red indicator on dashboard)
2. Care manager receives real-time alert with risk score and contributing factors
3. Mandatory follow-up within 7 days enforced by system
4. Post-discharge check-in scheduled for 48 hours
5. Medication reminders set to daily frequency
6. Care manager documents care plan

**Postconditions:** High-risk pathway activated; follow-up mandatory; care team notified

---

### UC-014: Multilingual Instruction Delivery

| Field | Value |
|-------|-------|
| **ID** | UC-014 |
| **Title** | Generate Discharge Instructions in Patient's Language |
| **Actors** | Documentation Agent, Patient Pat (P-05) |
| **Trigger** | Discharge event; patient's preferred language ≠ English |
| **Preconditions** | Language preference stored in FHIR `Patient.communication.language` |
| **BRD Refs** | FR-022, BR-004 |

**Main Flow:**

1. Documentation Agent reads language preference from FHIR
2. Agent generates instructions in patient's preferred language via LLM
3. Automated quality check validates medical terminology accuracy
4. Bilingual version (patient language + English) stored for care team reference
5. Portal displays instructions in patient's preferred language by default

**Postconditions:** Instructions in patient's language; Joint Commission BR-004 compliance met

---

### UC-015: Audit Trail Query

| Field | Value |
|-------|-------|
| **ID** | UC-015 |
| **Title** | Compliance Officer Queries Audit Trail |
| **Actors** | Compliance Officer |
| **Trigger** | Compliance review request or security incident |
| **Preconditions** | Compliance role assigned; audit logs intact |
| **BRD Refs** | FR-005, BR-012, BR-023, SEC-006 |

**Main Flow:**

1. Compliance Officer opens Audit Log module in Admin Settings
2. Filters by date range, user, event type, or data entity
3. System returns paginated, immutable records with user identity, action, timestamp, and IP
4. Officer exports report as CSV; PHI fields masked per role entitlement

**Postconditions:** Audit report generated; no PHI exposed beyond role entitlement

---

### UC-016: Admin User Provisioning

| Field | Value |
|-------|-------|
| **ID** | UC-016 |
| **Title** | IT Admin Provisions or Deprovisions User |
| **Actors** | IT Admin, Identity Provider |
| **Trigger** | New staff onboarding or staff departure |
| **Preconditions** | IT Admin authenticated with admin role |
| **BRD Refs** | FR-074, SEC-001, SEC-002 |

**Main Flow:**

1. IT Admin opens Admin Settings > User Management
2. Creates account; assigns role (Nurse / Physician / Pharmacist / BedManager / Admin)
3. System provisions account in Identity Provider via SCIM API
4. User receives onboarding email with SSO link and MFA setup instructions
5. Deprovisioning: admin disables account; all active sessions immediately revoked

**Postconditions:** User provisioned or deprovisioned; access enforced; audit entry created

---

### UC-017: Cancel ADT Event Handling

| Field | Value |
|-------|-------|
| **ID** | UC-017 |
| **Title** | Handle ADT Cancellation Event (A11/A12/A13) |
| **Actors** | EHR System, Transition Coordinator Agent |
| **Trigger** | HL7 ADT^A11, A12, or A13 received |
| **Preconditions** | Original ADT event processed; encounter record exists |
| **BRD Refs** | FR-006, FR-002 |

**Main Flow:**

1. MLLP listener receives cancellation; parser identifies cancel type
2. Coordinator Agent immediately halts all in-progress agent workflows for the encounter
3. Encounter status reverted to pre-event state; ADT event record updated to `CANCELLED`
4. Bed Management Agent reverses any assignments made by the cancelled event
5. Affected staff notified via SignalR

**Postconditions:** Encounter in correct prior state; no orphaned tasks; staff notified

---

### UC-018: ED Boarding Alert

| Field | Value |
|-------|-------|
| **ID** | UC-018 |
| **Title** | Trigger and Resolve ED Boarding Alert |
| **Actors** | Bed Management Agent, Coordinator Carol (P-04), ED Charge Nurse |
| **Trigger** | Patient has waited >2 hours for inpatient bed assignment |
| **Preconditions** | Patient admitted; no bed assigned within 2-hour window |
| **BRD Refs** | FR-043, BO-05 |

**Main Flow:**

1. Agent monitors time-to-bed-assignment for all pending admissions
2. At 2-hour threshold, agent fires ED Boarding Alert
3. Bed Manager and ED Charge Nurse receive push notification
4. Bed Manager opens boarding resolution workflow; system shows available beds and predicted discharges
5. Bed Manager assigns next available bed; alert cleared
6. Alert duration and resolution tracked for KPI reporting

**Postconditions:** Alert resolved; bed assigned; boarding time recorded for analytics

---

### UC-019: Analytics KPI Dashboard

| Field | Value |
|-------|-------|
| **ID** | UC-019 |
| **Title** | Manager Reviews Transition KPI Dashboard |
| **Actors** | Hospital Manager |
| **Trigger** | Manager logs in; navigates to Analytics module |
| **Preconditions** | Sufficient encounter data; manager role assigned |
| **BRD Refs** | FR-073, FR-075 |

**Main Flow:**

1. Manager selects date range and unit filter
2. System renders KPI charts: discharge documentation time, 30-day readmission rate, medication reconciliation completion rate, bed utilisation, patient satisfaction
3. Manager drills down into individual encounters
4. Manager exports report as CSV or PDF

**Postconditions:** KPI report generated; data de-identified per PRV-003

---

### UC-020: System & Agent Health Monitor

| Field | Value |
|-------|-------|
| **ID** | UC-020 |
| **Title** | Supervisor Monitors AI Agent Performance |
| **Actors** | IT Supervisor |
| **Trigger** | Routine monitoring or system alert |
| **Preconditions** | Supervisor authenticated; Agent Monitor module accessible |
| **BRD Refs** | FR-072, NFR-020 |

**Main Flow:**

1. Supervisor opens Agent Monitor screen
2. Views per-agent metrics: tasks processed, success rate, average duration, queue depth
3. Failed tasks displayed with error details and retry options
4. System health indicators show service uptime, Pub/Sub lag, Cloud SQL latency
5. Supervisor retries failed tasks or escalates to on-call engineer

**Postconditions:** Agent performance visible; failed tasks identified and actioned

---

## 6. Non-Functional Requirements

### 6.1 Performance

| ID | Requirement | Target | Measurement |
|----|-------------|--------|-------------|
| NFR-001 | Page load time (initial) | <2 seconds | Lighthouse, simulated 4G |
| NFR-002 | API response time (p95) | <500ms | Cloud Monitoring APM |
| NFR-003 | ADT event to notification (end-to-end) | <5 seconds | Event timestamp delta |
| NFR-004 | AI document generation | <30 seconds | Timer from trigger to draft-ready |
| NFR-005 | Concurrent user sessions | ≥500 | k6 load test |
| NFR-006 | SignalR push update latency | <1 second | Client-side delta |
| NFR-007 | Chatbot standard response time | <3 seconds | Client-side measurement |

### 6.2 Scalability

| ID | Requirement | Baseline | 10× Target |
|----|-------------|----------|------------|
| NFR-010 | Daily ADT events | 500 | 5,000 |
| NFR-011 | Active patient records | 10,000 | 100,000 |
| NFR-012 | API requests/day | 50,000 | 500,000 |
| NFR-013 | Storage growth | 10 GB/month | 100 GB/month |

*Architecture: Cloud Run auto-scaling; Cloud SQL read replicas; Pub/Sub horizontal fan-out*

### 6.3 Availability & Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-020 | System uptime | 99.9% (≤8.76 hours unplanned downtime/year) |
| NFR-021 | Planned maintenance window | Sundays 02:00–04:00 local time |
| NFR-022 | Recovery Time Objective (RTO) | <1 hour |
| NFR-023 | Recovery Point Objective (RPO) | <15 minutes |
| NFR-040 | Mean Time Between Failures (MTBF) | >720 hours |
| NFR-041 | Mean Time To Recovery (MTTR) | <30 minutes |
| NFR-042 | Data integrity | Zero data loss (PostgreSQL WAL + ACID) |
| NFR-043 | Backup frequency | Every 4 hours (Cloud SQL automated) |

### 6.4 Usability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-030 | New user training time to proficiency | <2 hours |
| NFR-031 | Task completion rate (UAT) | >95% |
| NFR-032 | User error rate (UAT) | <5% |
| NFR-033 | Mobile responsiveness | Full functionality on iOS/Android ≥375px viewport |
| NFR-034 | Accessibility compliance | WCAG 2.1 Level AA — all screens |

---

## 7. Business Rules

### 7.1 Clinical Rules

| ID | Rule | Source | Enforcement Point |
|----|------|--------|-------------------|
| BR-001 | All AI-generated discharge summaries require licensed clinician review and electronic approval before finalisation | Regulatory | Documentation Agent / UI |
| BR-002 | Medication reconciliation must be initiated within 24 hours of A01 admission event | CMS | Medication Reconciliation Agent |
| BR-003 | Patients with readmission risk score ≥0.7 must have follow-up appointment within 7 days | Clinical Best Practice | Follow-up Care Agent |
| BR-004 | Discharge instructions must be provided in the patient's preferred language | Joint Commission | Documentation Agent |
| BR-005 | Major drug-drug interactions must trigger immediate real-time alert to the responsible pharmacist | Patient Safety | Medication Reconciliation Agent |

### 7.2 Operational Rules

| ID | Rule | Source | Enforcement Point |
|----|------|--------|-------------------|
| BR-010 | ADT events must be fully processed within 5 seconds of receipt | SLA | MLLP Listener / Coordinator Agent |
| BR-011 | All AI-generated content must display "AI-Assisted — Review Required" until clinician approval | Transparency Policy | UI / Document Store |
| BR-012 | All patient data access must be logged with user identity, timestamp, and action | HIPAA | API Middleware / Audit Logger |
| BR-013 | User sessions must timeout after 30 minutes of inactivity | Security Policy | Angular AuthGuard / Backend JWT |
| BR-014 | Unacknowledged escalations must notify supervisor after 30 minutes | Operations | Follow-up Agent / Notification Service |

### 7.3 Data Rules

| ID | Rule | Source | Enforcement Point |
|----|------|--------|-------------------|
| BR-020 | All PHI fields must be encrypted at rest (AES-256) and in transit (TLS 1.3) | HIPAA | Cloud SQL CMEK / Cloud Run TLS |
| BR-021 | PHI must not appear in application logs, error messages, or telemetry | HIPAA | Log sanitisation middleware |
| BR-022 | Active patient records retained 7 years; thereafter archived to cold storage | Regulatory | Automated archival job |
| BR-023 | Audit logs are immutable; retained minimum 6 years | Compliance | Cloud SQL + Cloud Storage (WORM) |

---

## 8. Data Requirements

### 8.1 Core Data Entities

| Entity | Description | Source | Daily Volume |
|--------|-------------|--------|--------------|
| Patient | Demographics, language preference, MRN (PHI) | FHIR R4 | 50,000 active |
| Encounter | Admission/stay/discharge record | FHIR R4 + Internal | 500/day |
| ADTEvent | Parsed HL7 ADT events | HL7 Interface | 1,500/day |
| Medication | Pre-admission, inpatient, discharge lists (PHI) | FHIR R4 | 10/patient avg |
| AgentTask | Agent task records with status/results | System | 5,000/day |
| Document | AI-generated and approved clinical documents (PHI) | System | 2,000/day |
| AuditLog | Immutable access and action log | System | 50,000/day |
| User | Staff accounts, roles, preferences | Identity Provider | 1,000 total |

### 8.2 Domain Model

```
┌────────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│    Patient     │     │      Encounter      │     │    ADT Event     │
├────────────────┤     ├─────────────────────┤     ├──────────────────┤
│ PatientId (PK) │1──N │ EncounterId (PK)    │1──N │ EventId (PK)     │
│ MRN *          │     │ PatientId (FK)      │     │ EncounterId (FK) │
│ FirstName *    │     │ AdmitDate           │     │ EventType        │
│ LastName *     │     │ DischargeDate       │     │ EventTime        │
│ DOB *          │     │ Unit                │     │ SourceSystem     │
│ Gender         │     │ AttendingMD         │     │ ProcessedTime    │
│ Language       │     │ Status              │     │ AgentTriggered   │
│ Phone *        │     │ RiskScore           │     │ ProcessingStatus │
│ Email *        │     │ RiskTier            │     └──────────────────┘
└────────────────┘     └─────────────────────┘
      * PHI — encrypted                              │
                                                     │
            ┌────────────────────────────────────────┤
            │                   │                    │
            ▼                   ▼                    ▼
┌───────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│    Medication     │  │   AgentTask     │  │    Document      │
├───────────────────┤  ├─────────────────┤  ├──────────────────┤
│ MedicationId (PK) │  │ TaskId (PK)     │  │ DocumentId (PK)  │
│ EncounterId (FK)  │  │ EncounterId(FK) │  │ EncounterId (FK) │
│ DrugName          │  │ AgentType       │  │ DocumentType     │
│ Dosage            │  │ Status          │  │ Content *        │
│ Frequency         │  │ StartTime       │  │ Language         │
│ Route             │  │ EndTime         │  │ GeneratedBy      │
│ Status            │  │ Result          │  │ ReviewedBy       │
│ ConflictFlag      │  │ ErrorMessage    │  │ ApprovedAt       │
│ InteractionFlag   │  │ RetryCount      │  │ Status           │
└───────────────────┘  └─────────────────┘  └──────────────────┘
                                               * PHI — encrypted
```

### 8.3 Data Quality Rules

| Dimension | Requirement | Validation Mechanism |
|-----------|-------------|---------------------|
| Completeness | All required fields (MRN, AdmitDate, EventType) populated | API Pydantic validation; DB NOT NULL constraints |
| Accuracy | Patient demographics match FHIR source of truth | Nightly FHIR reconciliation job |
| Timeliness | ADT events processed within SLA; FHIR refreshed on-demand | Monitoring alerts on processing lag |
| Consistency | No duplicate encounters per MRN per admission date | Unique index on (MRN, AdmitDate) |
| Uniqueness | One Patient record per MRN | MRN unique constraint; FHIR identity merge logic |

---

## 9. Integration Requirements

### 9.1 Integration Inventory

| Integration | Direction | Protocol | Frequency | Risk |
|-------------|-----------|----------|-----------|------|
| EHR ADT Feed (HL7 v2.x MLLP) | Inbound | MLLP/TCP port 2575 | Real-time | High |
| EHR Patient Data (FHIR R4) | Inbound (read-only) | REST/HTTPS | On-demand | High |
| Google Vertex AI (LLM) | Outbound | REST/HTTPS | Per request | Medium |
| GCP Pub/Sub (Event Bus) | Internal | gRPC | Real-time | Low |
| Twilio (SMS/Voice) | Outbound | REST/HTTPS | Event-driven | Low |
| SendGrid (Email) | Outbound | REST/HTTPS | Event-driven | Low |
| Identity Provider (SSO) | Inbound | OIDC/OAuth2 | Per auth | Medium |
| SignalR Hub | Internal | WebSocket | Real-time | Low |

### 9.2 HL7 ADT Message Handling

| Message Type | Description | Agents Triggered |
|--------------|-------------|------------------|
| `ADT^A01` | Patient Admit | Coordinator → all agents |
| `ADT^A02` | Patient Transfer | Coordinator → Documentation, Bed Management |
| `ADT^A03` | Patient Discharge | Coordinator → all agents (discharge workflow) |
| `ADT^A04` | Patient Registration | Coordinator → Documentation |
| `ADT^A08` | Patient Info Update | Patient record sync only |
| `ADT^A11` | Cancel Admit | Coordinator → halt all workflows |
| `ADT^A12` | Cancel Transfer | Coordinator → revert transfer actions |
| `ADT^A13` | Cancel Discharge | Coordinator → halt discharge workflow |

### 9.3 FHIR R4 Resource Usage

| FHIR Resource | Usage | Access |
|---------------|-------|--------|
| `Patient` | Demographics, language preference | Read |
| `Encounter` | Admission/stay details | Read |
| `MedicationStatement` | Pre-admission medications | Read |
| `MedicationAdministration` | Inpatient medications | Read |
| `MedicationRequest` | Discharge prescriptions | Read |
| `AllergyIntolerance` | Drug allergy checks | Read |
| `Condition` | Diagnosis codes for summaries | Read |
| `Appointment` | Follow-up scheduling | Read (Write — Phase 2) |

---

## 10. Security & Compliance Requirements

### 10.1 Authentication & Authorisation

| ID | Requirement | Implementation |
|----|-------------|----------------|
| SEC-001 | OAuth 2.0 / OIDC with mandatory MFA for all staff roles | Hospital SSO integration; Angular AuthGuard |
| SEC-002 | RBAC with roles: Admin, Physician, Nurse, Pharmacist, BedManager, Patient, ReadOnly | JWT role claims; API policy enforcement |
| SEC-003 | Patient portal auth via OTP/magic link (no stored password) | Twilio Verify / email magic link |
| SEC-009 | Session timeout: 30 minutes inactivity (staff); 60 minutes (patients) | Angular idle timer + server-side JWT expiry |

### 10.2 Data Security

| ID | Requirement | Implementation |
|----|-------------|----------------|
| SEC-004 | Data encryption at rest: AES-256 | Cloud SQL Customer-Managed Encryption Keys (CMEK) |
| SEC-005 | Data encryption in transit: TLS 1.3 minimum | Cloud Run + load balancer TLS termination |
| SEC-006 | Immutable audit logging of all PHI access | Cloud SQL append-only audit table + Cloud Storage WORM |
| SEC-007 | PHI never in logs or error messages | Log sanitisation middleware; structured logging only |
| SEC-010 | Server-side input validation; parameterised queries only | FastAPI Pydantic; SQLAlchemy ORM |

### 10.3 API Security

| ID | Requirement | Implementation |
|----|-------------|----------------|
| SEC-011 | JWT bearer token required on all protected endpoints | FastAPI security dependency |
| SEC-012 | Rate limiting: 1,000 req/min per authenticated user; 100 req/min per IP (public) | Cloud Armor / API Gateway |
| SEC-013 | Weekly automated vulnerability scanning of container images | GCP Artifact Registry scanning |
| SEC-014 | Annual third-party penetration test | External security vendor |

### 10.4 Regulatory Compliance

| Regulation | Key Requirements | Implementation |
|------------|-----------------|----------------|
| HIPAA Privacy Rule | Minimum necessary access; consent management | RBAC + data-layer filtering |
| HIPAA Security Rule | AES-256, audit logs, access controls | SEC-001 through SEC-010 |
| HITECH | Breach notification; EHR interoperability | Incident response plan; FHIR integration |
| Joint Commission | Standardised handoff protocols; language access | Handoff checklists; multilingual instructions |
| CMS Conditions of Participation | Discharge planning requirements | Automated discharge workflow |

---

## 11. UI / UX Requirements

### 11.1 Screen Inventory

| Screen | Route | Primary Persona | Priority |
|--------|-------|-----------------|----------|
| Login | `/login` | All | Must Have |
| Dashboard Home | `/dashboard` | All Staff | Must Have |
| Patient List | `/patients` | Nurse, Physician | Must Have |
| Patient Detail | `/patients/:id` | All Staff | Must Have |
| Medication Review | `/patients/:id/medications` | Pharmacist | Must Have |
| Document Review | `/patients/:id/documents` | Physician, Nurse | Must Have |
| Bed Board | `/beds` | Bed Manager | Should Have |
| Agent Monitor | `/admin/agents` | Supervisor | Should Have |
| Analytics | `/analytics` | Manager | Should Have |
| Patient Portal | `/portal` | Patient | Must Have |
| Admin Settings | `/admin` | IT Admin | Must Have |

### 11.2 UI/UX Standards

| ID | Requirement | Specification |
|----|-------------|---------------|
| UI-001 | Responsive design | 1024px–2560px; fluid grid layout |
| UI-002 | Mobile support | ≥375px viewport; touch targets ≥44px |
| UI-003 | Healthcare colour palette | Blues/greens for neutral states; red/amber exclusively for alerts |
| UI-004 | WCAG 2.1 AA accessibility | Screen reader compatible; minimum 4.5:1 colour contrast ratio |
| UI-005 | Real-time notifications | Toast (top-right, 5s auto-dismiss) + badge counts + configurable sound |
| UI-006 | Dark mode | System-preference-aware; manual toggle available |
| UI-007 | Loading states | Skeleton loaders for all async content panels |
| UI-008 | Error handling | User-friendly messages with recovery action; no stack traces exposed to client |

---

## 12. Acceptance Criteria

### 12.1 Feature-Level Acceptance Criteria

| Feature | Acceptance Criteria | FR Refs |
|---------|---------------------|---------|
| ADT Event Processing | (1) All 8 event types processed correctly; (2) End-to-end latency ≤5 seconds under load; (3) 100% of events have audit trail entries | FR-001–006 |
| Documentation Agent | (1) Discharge summary generated ≤30 seconds; (2) ≥95% clinical accuracy in physician UAT; (3) All 5 languages produce valid output | FR-020–025 |
| Medication Reconciliation | (1) Drug interaction sensitivity ≥99% on test dataset; (2) All 3 medication lists shown in UI; (3) Priority alerts delivered in real-time | FR-030–036 |
| Bed Management | (1) Discharge time predictions within ±2 hours; (2) Bed board updates within 60 seconds; (3) ED boarding alerts fire at 2-hour threshold | FR-040–044 |
| Follow-up Care | (1) Risk score calculated ≤60 seconds of A03; (2) High-risk follow-up booked within 7 days; (3) Reminders delivered via SMS/email | FR-050–054 |
| Patient Communication | (1) Chatbot responds ≤3 seconds; (2) Urgency signals trigger emergency display immediately; (3) Escalation to care team ≤2 minutes | FR-060–065 |
| Dashboard | (1) Page load ≤2 seconds; (2) Role filtering verified for all 5 roles; (3) SignalR updates visible within 1 second | FR-070–075 |

### 12.2 System Acceptance Criteria

| Category | Criteria | Test Method |
|----------|----------|-------------|
| Performance | 95% of API requests ≤500ms under 500 concurrent users | k6 load test |
| Availability | 99.9% uptime over 30-day post-go-live period | Cloud Monitoring uptime check |
| Security | Pass external penetration test; zero OWASP Top 10 critical findings | Third-party assessment |
| Usability | ≥80% satisfaction score in UAT survey across all staff personas | UAT survey |
| Integration | 100% of HL7 test messages parsed correctly; FHIR data retrieved without error | Integration test suite |
| Accessibility | WCAG 2.1 AA audit passes for all Must Have screens | axe-core automated + manual review |

---

## 13. Assumptions & Constraints

### 13.1 Assumptions

| ID | Assumption | Impact if Invalid |
|----|------------|-------------------|
| A-01 | EHR system transmits HL7 v2.x ADT messages via MLLP | Custom integration adapter required |
| A-02 | Hospital has FHIR R4 REST endpoint accessible from GCP | Data access limited; CSV import fallback needed |
| A-03 | Staff have basic computer literacy (web browser, email) | Extended training programme required |
| A-04 | Reliable internet connectivity ≥10 Mbps in hospital | Offline/PWA caching strategy required |
| A-05 | GCP services (Cloud Run, Vertex AI) available in required region | Alternative LLM or cloud region needed |
| A-06 | Budget approved for Vertex AI API usage | Fall back to open-source LLM (e.g., LLaMA 3) |

### 13.2 Constraints

| ID | Constraint | Impact |
|----|------------|--------|
| C-01 | 2-week development sprint timeline | Must Have requirements only |
| C-02 | 6-developer team (2 FE, 2 BE, 1 AI/ML, 1 DevOps) | All workstreams must run in parallel |
| C-03 | No EHR write-back in Phase 1 | Read-only FHIR integration |
| C-04 | HIPAA compliance mandatory from day 1 | All PHI handling reviewed before deployment |
| C-05 | GCP-only infrastructure | No AWS/Azure services permitted |
| C-06 | Must integrate with existing hospital SSO | OAuth2/OIDC adapter required |

---

## 14. Requirements Traceability Matrix

| FR ID | Description (Summary) | UC Coverage | BO Ref | Priority |
|-------|-----------------------|-------------|--------|----------|
| FR-001 | HL7 ADT real-time processing ≤5 seconds | UC-001, UC-002, UC-003, UC-017 | BO-06 | Must Have |
| FR-002 | All 8 ADT event types supported | UC-001–003, UC-017–018 | BO-06 | Must Have |
| FR-003 | HL7 message parsing to domain model | UC-001–003 | BO-06 | Must Have |
| FR-004 | Agent trigger within 2 seconds of ADT persistence | UC-001–003 | BO-03, BO-06 | Must Have |
| FR-005 | Immutable ADT audit trail | UC-015 | BO-07 | Must Have |
| FR-006 | Cancellation event (A11/A12/A13) handling | UC-017 | BO-06 | Must Have |
| FR-010 | Coordinator agent orchestration | UC-001–003 | BO-06 | Must Have |
| FR-011 | Task tracking and SLA escalation | UC-009, UC-013 | BO-06 | Must Have |
| FR-012 | SignalR real-time updates ≤1 second | UC-010 | BO-03 | Must Have |
| FR-013 | Context-aware handoff checklists | UC-002 | BO-03, BO-06 | Should Have |
| FR-014 | Task status API endpoint | UC-010, UC-020 | BO-06 | Must Have |
| FR-020 | Auto-generate discharge summary ≤30 seconds | UC-004, UC-003 | BO-03 | Must Have |
| FR-021 | Patient-friendly discharge instructions | UC-003, UC-011 | BO-04 | Must Have |
| FR-022 | Multilingual document support (5 languages) | UC-014 | BO-10 | Should Have |
| FR-023 | Documentation completeness check | UC-004, UC-009 | BO-07 | Must Have |
| FR-024 | Dual-pane human review and inline editing | UC-009 | BO-07 | Must Have |
| FR-025 | AI-Assisted label on all generated content | UC-009 | BO-07 | Must Have |
| FR-030 | 3-list medication comparison | UC-005 | BO-01 | Must Have |
| FR-031 | Drug-drug interaction detection ≥99% sensitivity | UC-005, UC-012 | BO-01 | Must Have |
| FR-032 | Duplicate medication detection | UC-005 | BO-01 | Must Have |
| FR-033 | Missing chronic medication alert | UC-005 | BO-01 | Should Have |
| FR-034 | Patient medication change summary | UC-005, UC-003 | BO-04 | Must Have |
| FR-035 | Real-time pharmacist alert for high-risk cases | UC-012 | BO-01 | Must Have |
| FR-036 | Reconciliation within 24 hours of admission | UC-005 | BO-01 | Must Have |
| FR-040 | Discharge time ML prediction (±2 hours) | UC-006 | BO-05 | Should Have |
| FR-041 | Real-time bed availability board | UC-006 | BO-05 | Must Have |
| FR-042 | Optimal bed assignment scoring | UC-006 | BO-05 | Should Have |
| FR-043 | ED boarding alert at 2-hour threshold | UC-018 | BO-05 | Must Have |
| FR-044 | Housekeeping notification on discharge | UC-006 | BO-05 | Should Have |
| FR-050 | Automated follow-up scheduling | UC-007 | BO-02 | Should Have |
| FR-051 | Medication reminder SMS/email | UC-007, UC-011 | BO-04 | Should Have |
| FR-052 | 30-day readmission risk ML score | UC-007, UC-013 | BO-02, BO-09 | Must Have |
| FR-053 | Post-discharge concern escalation ≤15 minutes | UC-008, UC-013 | BO-02 | Must Have |
| FR-054 | 48-hour check-in for risk ≥0.5 | UC-013 | BO-02 | Should Have |
| FR-060 | 24/7 patient chatbot (mobile browser) | UC-008, UC-011 | BO-04 | Must Have |
| FR-061 | Scoped chatbot Q&A | UC-008 | BO-04 | Must Have |
| FR-062 | Chatbot escalation ≤2 minutes | UC-008 | BO-04 | Must Have |
| FR-063 | Emergency urgency signal detection | UC-008 | Safety | Must Have |
| FR-064 | Voice-to-text input | UC-008 | BO-04 | Could Have |
| FR-065 | Transcript storage against encounter | UC-008 | BO-07 | Must Have |
| FR-070 | Live ADT event feed via SignalR | UC-010 | BO-06 | Must Have |
| FR-071 | Risk score colour-coded display | UC-010 | BO-09 | Must Have |
| FR-072 | Per-agent task status display | UC-020 | BO-06 | Must Have |
| FR-073 | Analytics KPI dashboards | UC-019 | BO-02–05 | Should Have |
| FR-074 | Role-based dashboard view filtering | UC-010 | BO-06 | Must Have |
| FR-075 | Analytics report export (CSV/PDF) | UC-015, UC-019 | BO-07 | Should Have |

---

## 15. Glossary

| Term | Definition |
|------|------------|
| ADT | Admission, Discharge, Transfer — core HL7 patient movement event types |
| AI Agent | Autonomous LangChain-based component performing a specialised care transition task |
| FHIR | Fast Healthcare Interoperability Resources (R4) — REST-based healthcare data standard |
| HL7 | Health Level Seven — healthcare messaging standard (v2.x used for ADT feed) |
| LLM | Large Language Model — AI model powering document generation and chatbot |
| MLLP | Minimal Lower Layer Protocol — TCP transport for HL7 v2 messages |
| MRN | Medical Record Number — unique patient identifier within the hospital |
| PHI | Protected Health Information — patient data regulated under HIPAA |
| LangChain | Python framework for building multi-agent AI orchestration workflows |
| FastAPI | High-performance Python web framework used for SmartHandoff API |
| Vertex AI | Google Cloud AI platform providing Gemini LLM API |
| Scikit-learn | Python ML library for readmission risk and discharge time prediction models |
| SignalR | WebSocket library for real-time dashboard push updates |
| RBAC | Role-Based Access Control — permission model based on user roles |
| RTO | Recovery Time Objective — maximum acceptable system downtime after failure |
| RPO | Recovery Point Objective — maximum acceptable data loss window |
| WCAG | Web Content Accessibility Guidelines — international accessibility standard |
| MTBF | Mean Time Between Failures |
| MTTR | Mean Time To Recovery |

---

*End of SmartHandoff SRS — Version 1.0 | Generated: 2026-07-13*
