# SmartHandoff — Functional Requirements & Use Case Specification

---

| Field | Value |
|---|---|
| **Document ID** | SPEC-001 |
| **Version** | 1.0 |
| **Date** | 2026-07-10 |
| **Status** | Draft |
| **Source BRD** | BRD_DOCUMENT.md v1.0 |
| **Owner** | SmartHandoff Project Team |

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Scope Boundaries](#2-scope-boundaries)
3. [Actors & Personas](#3-actors--personas)
4. [Functional Requirements](#4-functional-requirements)
   - [4.1 ADT Event Processing](#41-adt-event-processing)
   - [4.2 Transition Coordinator Agent](#42-transition-coordinator-agent)
   - [4.3 Documentation Agent](#43-documentation-agent)
   - [4.4 Medication Reconciliation Agent](#44-medication-reconciliation-agent)
   - [4.5 Bed Management Agent](#45-bed-management-agent)
   - [4.6 Follow-up Care Agent](#46-follow-up-care-agent)
   - [4.7 Patient Communication Agent](#47-patient-communication-agent)
   - [4.8 Dashboard & Reporting](#48-dashboard--reporting)
   - [4.9 Authentication & Authorization](#49-authentication--authorization)
5. [Use Cases](#5-use-cases)
6. [Business Rules](#6-business-rules)
7. [Data Requirements](#7-data-requirements)
8. [Acceptance Criteria](#8-acceptance-criteria)
9. [Traceability Matrix](#9-traceability-matrix)

---

## 1. System Overview

**SmartHandoff** is an AI-powered care transition orchestrator that automates and coordinates healthcare workflows during Admission, Discharge, and Transfer (ADT) events. The system deploys six specialized AI agents — Transition Coordinator, Documentation, Medication Reconciliation, Bed Management, Follow-up Care, and Patient Communication — that collaborate in real-time to reduce medication errors, decrease readmissions, and improve discharge documentation efficiency.

### Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Angular 17 PWA |
| Backend API | Python FastAPI with WebSockets |
| AI Agents | LangChain multi-agent framework |
| ML Models | Scikit-learn |
| LLM | Google Vertex AI |
| Database | Cloud SQL (PostgreSQL) |
| Messaging | GCP Pub/Sub |
| Real-time | SignalR |
| Cloud | Google Cloud Platform (GCP) |
| Notifications | Twilio (SMS), SendGrid (Email) |

---

## 2. Scope Boundaries

### In Scope (Phase 1 — MVP)

- Real-time HL7 ADT event processing (A01, A02, A03, A04, A08, A11, A12, A13)
- Six AI agent workflows (Transition Coordinator, Documentation, Medication Reconciliation, Bed Management, Follow-up Care, Patient Communication)
- Care team dashboard and patient portal (Angular PWA)
- Read-only FHIR R4 integration with EHR systems
- Role-based access control (RBAC) with OAuth 2.0 / OIDC + MFA
- Real-time notifications via SignalR
- Readmission risk scoring (ML)
- Multilingual discharge instructions (minimum 5 languages)
- GCP Cloud infrastructure

### Out of Scope (Phase 1)

| Item | Deferred To |
|---|---|
| EHR write-back integration | Phase 2 |
| Voice-enabled interfaces | Phase 2 |
| IoT bed sensors | Phase 3 |
| Insurance pre-authorization | Phase 3 |
| Multi-hospital federation | Phase 3 |

---

## 3. Actors & Personas

| Actor ID | Actor | Description | Primary Interaction |
|---|---|---|---|
| ACT-01 | Floor Nurse | Bedside care provider completing handoff tasks | Dashboard, patient list, task completion |
| ACT-02 | Attending Physician | Clinician reviewing and approving patient transitions | Summaries, approvals, medication review |
| ACT-03 | Clinical Pharmacist | Specialist reviewing medication safety | Medication reconciliation interface |
| ACT-04 | Bed Manager | Coordinator managing patient flow and bed availability | Bed board, bed assignment |
| ACT-05 | Patient | Discharged or transitioning patient | Patient portal, chatbot |
| ACT-06 | IT Administrator | System configuration and user management | Admin settings |
| ACT-07 | Supervisor / Manager | Oversight of system performance and KPIs | Analytics, agent monitor |
| ACT-08 | EHR System | External source system sending HL7 ADT messages | HL7 MLLP feed |
| ACT-09 | AI Agent (System) | Autonomous software agent performing AI-driven tasks | Backend agent workflows |
| ACT-10 | Compliance Officer | Reviewer of audit trails and regulatory adherence | Audit logs, reports |

---

## 4. Functional Requirements

> **Note:** FR-XXX IDs are stable and align with BRD Section 6. IDs FR-001–FR-074 are directly derived from BRD v1.0. Additional requirements introduced in this spec begin at FR-080.

---

### 4.1 ADT Event Processing

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-001 | The system shall receive and process HL7 ADT messages in real-time via MLLP/TCP. | Must Have | ADT message received and parsed within 5 seconds of arrival | BRD §6.1 |
| FR-002 | The system shall support the following HL7 ADT event types: A01 (Admit), A02 (Transfer), A03 (Discharge), A04 (Register), A08 (Update), A11 (Cancel Admit), A12 (Cancel Transfer), A13 (Cancel Discharge). | Must Have | All 8 event types parsed without error; unknown types logged and rejected gracefully | BRD §6.1 |
| FR-003 | The system shall trigger the appropriate AI agent workflows based on the received ADT event type. | Must Have | Correct agent(s) invoked for each event type per agent routing table | BRD §6.1 |
| FR-004 | The system shall maintain a complete, immutable audit trail of all ADT events including event type, timestamp, source system, patient MRN, and processing status. | Must Have | Audit log record created for every ADT event; records are write-once | BRD §6.1 |
| FR-005 | The system shall publish ADT events to GCP Pub/Sub for downstream agent consumption. | Must Have | Event published to topic within 1 second of parsing | BRD §10.1 |
| FR-006 | The system shall deduplicate ADT events with the same message ID within a 60-second window. | Must Have | Duplicate messages within window do not trigger duplicate agent invocations | Derived |

---

### 4.2 Transition Coordinator Agent

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-010 | The Transition Coordinator Agent shall orchestrate task assignment and sequencing across all other agents upon receiving an ADT trigger. | Must Have | All applicable agents receive tasks within 5 seconds of ADT event processing | BRD §6.2 |
| FR-011 | The agent shall track task completion status for all active care transitions and escalate tasks overdue by more than 30 minutes to the assigned supervisor. | Must Have | Escalation notification sent at t+30 min for any incomplete task; supervisor receives in-app alert | BRD §6.2 |
| FR-012 | The agent shall push real-time status updates to connected dashboard clients via SignalR within 1 second of a status change. | Must Have | SignalR message delivered to all subscribed clients within 1 second | BRD §6.2 |
| FR-013 | The agent shall generate a context-aware handoff checklist for each patient based on ADT event type, patient acuity, and active conditions. | Should Have | Checklist generated within 10 seconds; items tailored to patient risk score and event type | BRD §6.2 |
| FR-014 | The agent shall log all orchestration decisions and task assignments with timestamps for audit purposes. | Must Have | Orchestration log record created for each agent invocation | Derived |

---

### 4.3 Documentation Agent

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-020 | The Documentation Agent shall auto-generate a draft discharge summary from patient encounter data (diagnoses, procedures, medications, vitals) within 30 seconds of a Discharge (A03) event. | Must Have | Draft summary generated within 30 seconds; summary includes all required clinical sections | BRD §6.3 |
| FR-021 | The agent shall generate patient-friendly discharge instructions in plain language (6th-grade reading level) derived from the clinical discharge summary. | Must Have | Instructions generated; Flesch-Kincaid readability score ≥ 60; all discharge topics covered | BRD §6.3 |
| FR-022 | The agent shall generate discharge instructions in a minimum of 5 languages: English, Spanish, French, Mandarin, and Arabic. | Should Have | Instructions generated in all 5 target languages; content accuracy validated by back-translation | BRD §6.3 |
| FR-023 | The agent shall perform a pre-discharge documentation completeness check and block the discharge workflow if any required document is missing. | Must Have | Discharge blocked until all required fields are present; blocking reason displayed to user | BRD §6.3 |
| FR-024 | The agent shall present all AI-generated document content for clinician review and enable inline editing before finalization. | Must Have | Clinician can view, edit, and approve/reject generated content; final version records reviewer identity | BRD §6.3 |
| FR-025 | All AI-generated content shall be clearly labelled "AI-Assisted" in the UI and in the document metadata. | Must Have | Label present on all generated documents; metadata field `generatedBy` set to agent identifier | BRD §8.2 |

---

### 4.4 Medication Reconciliation Agent

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-030 | The Medication Reconciliation Agent shall retrieve and compare pre-admission, current inpatient, and discharge medication lists for every active encounter. | Must Have | Three-list comparison populated within 30 seconds of trigger; discrepancies flagged | BRD §6.4 |
| FR-031 | The agent shall detect and flag drug-drug interactions using a validated clinical drug database with sensitivity ≥ 99%. | Must Have | Interaction alert generated for all known major interactions; alert delivered to pharmacist in real-time | BRD §6.4 |
| FR-032 | The agent shall identify and flag duplicate medications (same drug, different brand or dosage form). | Must Have | Duplicate flag raised when ≥2 entries map to the same RxNorm code | BRD §6.4 |
| FR-033 | The agent shall highlight chronic medications that are absent from the current medication list. | Should Have | Alert generated for each chronic medication not present in the inpatient list | BRD §6.4 |
| FR-034 | The agent shall generate a patient-readable medication change summary listing added, discontinued, and modified medications. | Must Have | Summary generated in plain language; lists all changes since admission | BRD §6.4 |
| FR-035 | The agent shall send a priority alert to the responsible pharmacist when a reconciliation case involves ≥3 drug interactions, ≥10 medications, or any high-alert medication class. | Must Have | Alert delivered to pharmacist within 60 seconds of reconciliation completion | BRD §6.4 |
| FR-036 | Medication reconciliation shall be completed within 24 hours of admission as required by CMS standards. | Must Have | System records reconciliation timestamp; SLA breach alert generated at t+22 hours if incomplete | BRD §8.1 |

---

### 4.5 Bed Management Agent

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-040 | The Bed Management Agent shall predict estimated discharge time for each inpatient encounter using an ML model trained on historical encounter data, with prediction accuracy within ±2 hours. | Should Have | Prediction generated within 60 seconds of admission; MAE ≤ 2 hours on held-out test set | BRD §6.5 |
| FR-041 | The agent shall provide a real-time bed availability dashboard displaying bed status (Available, Occupied, Pending Discharge, Under Cleaning) for all units. | Must Have | Dashboard reflects current status; updates within 5 seconds of status change | BRD §6.5 |
| FR-042 | The agent shall recommend the optimal bed assignment for incoming patients based on acuity, unit specialization, and isolation requirements. | Should Have | Recommendation generated within 10 seconds; rationale displayed to bed manager | BRD §6.5 |
| FR-043 | The agent shall generate an alert when Emergency Department boarding time exceeds a configurable threshold (default: 2 hours). | Must Have | Alert generated and delivered to ED manager within 1 minute of threshold breach | BRD §6.5 |
| FR-044 | The agent shall track bed turnaround time (discharge to next admission) and alert when turnaround exceeds the configured SLA. | Should Have | Metric tracked per bed; alert generated on SLA breach | Derived |

---

### 4.6 Follow-up Care Agent

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-050 | The Follow-up Care Agent shall schedule a post-discharge follow-up appointment with the patient's primary care provider or specialist before the patient leaves the hospital. | Should Have | Appointment booking confirmation generated before discharge; confirmation sent to patient via SMS/email | BRD §6.6 |
| FR-051 | The agent shall send automated medication reminders to discharged patients via SMS and/or email at configured intervals (e.g., twice daily for 7 days). | Should Have | Reminder messages delivered via configured channel; patient can opt out | BRD §6.6 |
| FR-052 | The agent shall calculate a 30-day readmission risk score (0.0–1.0) for each patient using an ML model upon discharge. | Must Have | Risk score computed within 60 seconds of discharge; score stored in encounter record | BRD §6.6 |
| FR-053 | The agent shall automatically schedule a follow-up appointment within 7 days of discharge for patients with a readmission risk score ≥ 0.7. | Must Have | Appointment booked within 5 minutes of discharge for high-risk patients; care manager notified | BRD §6.6, §8.1 |
| FR-054 | The agent shall escalate patient-reported symptoms or concerns received via the patient portal to the care team with severity classification within 5 minutes. | Must Have | Escalation notification delivered to assigned nurse within 5 minutes of concern submission | BRD §6.6 |
| FR-055 | Escalations not addressed by the care team within 30 minutes shall automatically notify the supervisor. | Must Have | Supervisor alert generated at t+30 minutes for unacknowledged escalations | BRD §8.2 |

---

### 4.7 Patient Communication Agent

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-060 | The Patient Communication Agent shall provide a 24/7 chatbot interface accessible from the patient portal, with response time ≤ 3 seconds for standard queries. | Must Have | Chatbot available continuously; 95th-percentile response time ≤ 3 seconds | BRD §6.7 |
| FR-061 | The chatbot shall answer questions about discharge instructions, medications, and follow-up appointments based on the patient's specific encounter data. | Must Have | Responses reference patient-specific data; no generic placeholder responses | BRD §6.7 |
| FR-062 | The chatbot shall detect and escalate queries classified as urgent (e.g., chest pain, allergic reaction) to the on-call care team within 2 minutes. | Must Have | Escalation triggered within 2 minutes; patient notified that a human will contact them | BRD §6.7 |
| FR-063 | The chatbot shall support voice-to-text input for accessibility. | Could Have | Voice input transcribed with ≥ 90% accuracy; text submitted to chatbot pipeline | BRD §6.7 |
| FR-064 | The chatbot shall present responses in the patient's preferred language as recorded in their patient record. | Must Have | Language preference applied automatically; patient can switch language mid-session | Derived |

---

### 4.8 Dashboard & Reporting

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-070 | The system shall display a real-time ADT event feed on the care team dashboard, showing event type, patient MRN (masked), unit, and timestamp. | Must Have | New ADT events appear on dashboard within 2 seconds of processing | BRD §6.8 |
| FR-071 | The dashboard shall display a readmission risk score and acuity flag for each current patient. | Must Have | Risk scores visible for all current inpatients; high-risk patients visually distinguished | BRD §6.8 |
| FR-072 | The dashboard shall display agent task status (Pending, In Progress, Completed, Failed) for all active AI agent workflows. | Must Have | Agent monitor shows live status; failed tasks highlighted with error detail | BRD §6.8 |
| FR-073 | The system shall provide an analytics module displaying transition metrics including average discharge time, readmission rate, medication reconciliation completion rate, and ED boarding time. | Should Have | All defined KPIs displayed with daily/weekly/monthly filters | BRD §6.8 |
| FR-074 | The dashboard shall support role-based views: Nurse view, Physician view, Pharmacist view, Bed Manager view, Supervisor view, and Admin view. | Must Have | Each role sees only the widgets and data relevant to their role; RBAC enforced at data layer | BRD §6.8 |
| FR-080 | The system shall provide a patient list screen with search and filter capabilities (by unit, attending physician, risk score, ADT event type). | Must Have | Search returns results within 500ms; filters applied correctly | Derived |
| FR-081 | The system shall provide a patient detail screen displaying demographics, current medications, active tasks, generated documents, and risk score in a single view. | Must Have | All data sections populated within 2 seconds of page load | Derived |

---

### 4.9 Authentication & Authorization

| Req ID | Requirement | Priority | Acceptance Criterion | Source |
|---|---|---|---|---|
| FR-085 | The system shall authenticate all users via OAuth 2.0 / OIDC integrated with the hospital's existing SSO provider. | Must Have | Login succeeds using hospital SSO credentials; no separate password store | BRD §12.2 |
| FR-086 | The system shall enforce Multi-Factor Authentication (MFA) for all user accounts. | Must Have | MFA challenge presented on every login; login rejected without successful MFA | BRD §12.2 |
| FR-087 | The system shall enforce Role-Based Access Control (RBAC) restricting each user's data access and UI capabilities to their assigned role. | Must Have | Cross-role data access returns 403; RBAC enforced at API and UI layer | BRD §12.2 |
| FR-088 | User sessions shall automatically time out after 30 minutes of inactivity. | Must Have | Session invalidated at t+30 min; user redirected to login | BRD §8.2 |

---

## 5. Use Cases

> Use cases are numbered UC-001 through UC-020. Each use case maps to one or more Functional Requirements.

---

### UC-001 — Receive and Route ADT Event

| Field | Detail |
|---|---|
| **Use Case ID** | UC-001 |
| **Title** | Receive and Route ADT Event |
| **Actors** | ACT-08 (EHR System), ACT-09 (AI Agent System) |
| **Trigger** | EHR system transmits an HL7 ADT message |
| **Preconditions** | HL7 MLLP connection is active; SmartHandoff API is running |
| **Mapped FRs** | FR-001, FR-002, FR-003, FR-004, FR-005, FR-006 |

**Main Success Scenario:**

1. EHR sends HL7 ADT message (A01/A02/A03/A04/A08/A11/A12/A13) over MLLP/TCP.
2. System parses the HL7 message, extracts event type, patient MRN, timestamp, and source system.
3. System performs deduplication check using message ID and 60-second window.
4. System creates an immutable audit log entry for the ADT event.
5. System publishes the parsed event to GCP Pub/Sub.
6. Transition Coordinator Agent subscribes to the Pub/Sub topic and receives the event.
7. Agent determines the applicable agent workflow(s) based on event type.
8. Agent dispatches task assignments to applicable agents.
9. SignalR pushes an event notification to all connected dashboard clients.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 2a | Message format is invalid | System logs parse error; sends HL7 NAK acknowledgement; generates alert |
| 3a | Duplicate message detected | Message discarded; deduplication counter incremented in audit log |
| 5a | Pub/Sub publish fails | Retry up to 3 times with exponential backoff; dead-letter queue after 3 failures |

---

### UC-002 — Orchestrate Patient Admission

| Field | Detail |
|---|---|
| **Use Case ID** | UC-002 |
| **Title** | Orchestrate Patient Admission |
| **Actors** | ACT-01 (Floor Nurse), ACT-02 (Attending Physician), ACT-09 (AI Agent System) |
| **Trigger** | ADT^A01 Admit event processed |
| **Preconditions** | UC-001 completed successfully; patient record accessible via FHIR |
| **Mapped FRs** | FR-003, FR-010, FR-013, FR-030, FR-036, FR-041, FR-052 |

**Main Success Scenario:**

1. Transition Coordinator Agent receives A01 event.
2. Agent retrieves patient demographics and clinical history from FHIR R4 endpoint.
3. Agent generates a context-aware admission handoff checklist.
4. Agent dispatches tasks to: Medication Reconciliation Agent (begin reconciliation), Bed Management Agent (confirm bed assignment), Follow-up Care Agent (record baseline risk data).
5. Medication Reconciliation Agent retrieves pre-admission medications and begins three-list comparison.
6. Bed Management Agent confirms bed assignment and updates bed board status.
7. Nurse is notified via dashboard of admission and pending tasks.
8. Readmission risk baseline is recorded for the encounter.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 2a | FHIR endpoint unavailable | Agent retries 3 times; uses cached patient data if available; alert sent to IT |
| 5a | Pre-admission medication list unavailable | Pharmacist alerted to obtain medication history manually |

---

### UC-003 — Orchestrate Patient Transfer

| Field | Detail |
|---|---|
| **Use Case ID** | UC-003 |
| **Title** | Orchestrate Patient Transfer |
| **Actors** | ACT-01 (Floor Nurse), ACT-04 (Bed Manager), ACT-09 (AI Agent System) |
| **Trigger** | ADT^A02 Transfer event processed |
| **Preconditions** | Patient has an active admission encounter |
| **Mapped FRs** | FR-003, FR-010, FR-011, FR-012, FR-013, FR-041, FR-042 |

**Main Success Scenario:**

1. Transition Coordinator Agent receives A02 event.
2. Agent creates a transfer handoff checklist for the receiving unit.
3. Agent notifies the receiving unit nurse via SignalR alert.
4. Bed Management Agent updates bed status in the sending unit (Pending Clean) and receiving unit (Occupied).
5. Agent marks the transfer handoff as pending completion.
6. Receiving nurse confirms patient receipt on the dashboard, completing the handoff.
7. Audit log updated with transfer completion timestamp.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 6a | Handoff not confirmed within 30 minutes | Escalation sent to supervisor per FR-011 |

---

### UC-004 — Orchestrate Patient Discharge

| Field | Detail |
|---|---|
| **Use Case ID** | UC-004 |
| **Title** | Orchestrate Patient Discharge |
| **Actors** | ACT-01 (Floor Nurse), ACT-02 (Attending Physician), ACT-03 (Clinical Pharmacist), ACT-09 (AI Agent System) |
| **Trigger** | ADT^A03 Discharge event processed |
| **Preconditions** | Patient has an active admission encounter; discharge order entered in EHR |
| **Mapped FRs** | FR-003, FR-010, FR-020, FR-021, FR-023, FR-030, FR-052, FR-053 |

**Main Success Scenario:**

1. Transition Coordinator Agent receives A03 event.
2. Agent dispatches tasks to: Documentation Agent (generate discharge summary and instructions), Medication Reconciliation Agent (finalize reconciliation), Follow-up Care Agent (compute risk score and schedule follow-up).
3. Documentation Agent drafts discharge summary and patient instructions.
4. Documentation completeness check runs; all required documents confirmed present.
5. Physician receives review notification; reviews and approves documents via the dashboard.
6. Medication Reconciliation Agent delivers reconciled medication list and patient change summary.
7. Follow-up Care Agent computes readmission risk score.
8. If risk score ≥ 0.7, a follow-up appointment is scheduled within 7 days.
9. Patient receives discharge instructions and medication summary via portal and/or print.
10. Bed Management Agent updates bed status to Pending Cleaning.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 4a | Required document missing | Discharge workflow blocked; nurse and physician notified with specific missing items |
| 5a | Physician rejects AI-generated summary | Document returned to Documentation Agent with revision notes; revised draft generated |

---

### UC-005 — Generate Discharge Summary

| Field | Detail |
|---|---|
| **Use Case ID** | UC-005 |
| **Title** | Generate Discharge Summary |
| **Actors** | ACT-02 (Attending Physician), ACT-09 (Documentation Agent) |
| **Trigger** | Discharge workflow triggered (UC-004 Step 2) |
| **Preconditions** | Patient encounter data (diagnoses, medications, procedures) accessible via FHIR |
| **Mapped FRs** | FR-020, FR-024, FR-025 |

**Main Success Scenario:**

1. Documentation Agent retrieves encounter data from FHIR: diagnoses (ICD-10), procedures (CPT), current medications, allergies, vitals, lab results.
2. Agent sends structured data to Vertex AI LLM with a discharge summary prompt template.
3. LLM generates a draft discharge summary within 30 seconds.
4. Summary is labelled "AI-Assisted" and stored as a draft document.
5. Physician receives in-app notification to review the draft.
6. Physician reviews, edits if necessary, and approves the summary.
7. Document status updated to Finalized; reviewer identity and timestamp recorded.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 2a | Vertex AI API call fails | Agent retries once after 5 seconds; if second failure, physician notified to complete summary manually |
| 6a | Physician requests revision | Physician enters notes; agent regenerates summary incorporating feedback |

---

### UC-006 — Generate Patient Discharge Instructions

| Field | Detail |
|---|---|
| **Use Case ID** | UC-006 |
| **Title** | Generate Patient Discharge Instructions |
| **Actors** | ACT-05 (Patient), ACT-09 (Documentation Agent) |
| **Trigger** | Discharge summary approved (UC-005 Step 7) |
| **Preconditions** | Approved discharge summary exists; patient language preference recorded |
| **Mapped FRs** | FR-021, FR-022, FR-024, FR-025, FR-064 |

**Main Success Scenario:**

1. Documentation Agent retrieves the approved discharge summary and patient language preference.
2. Agent generates plain-language instructions (target: 6th-grade reading level) from the clinical summary.
3. If patient language preference is not English, agent requests translation from Vertex AI.
4. Instructions are stored and labelled "AI-Assisted".
5. Clinician reviews and approves the instructions.
6. Instructions are made available on the patient portal and optionally printed.

---

### UC-007 — Perform Medication Reconciliation

| Field | Detail |
|---|---|
| **Use Case ID** | UC-007 |
| **Title** | Perform Medication Reconciliation |
| **Actors** | ACT-03 (Clinical Pharmacist), ACT-09 (Medication Reconciliation Agent) |
| **Trigger** | Admission event (UC-002) or Discharge event (UC-004) |
| **Preconditions** | Pre-admission and current medication lists available |
| **Mapped FRs** | FR-030, FR-031, FR-032, FR-033, FR-034, FR-035, FR-036 |

**Main Success Scenario:**

1. Medication Reconciliation Agent retrieves pre-admission, inpatient, and (for discharge) discharge medication lists from FHIR.
2. Agent maps all medications to RxNorm codes.
3. Agent performs three-list comparison, flagging: additions, discontinuations, dose changes, duplicates, missing chronic medications.
4. Agent queries the drug interaction database for all active medication combinations.
5. Agent generates interaction alerts for identified drug-drug interactions.
6. Agent classifies the reconciliation case complexity (low/medium/high).
7. If high complexity (≥3 interactions, ≥10 medications, or high-alert class), priority alert sent to pharmacist.
8. Pharmacist reviews the reconciliation report, resolves flags, and approves the final medication list.
9. Patient medication change summary generated for patient-facing use.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 1a | Medication list unavailable from FHIR | Pharmacist alerted; reconciliation marked incomplete pending manual input |
| 8a | Pharmacist identifies additional issue | Pharmacist adds annotation; prescribing physician notified |

---

### UC-008 — Monitor Bed Availability

| Field | Detail |
|---|---|
| **Use Case ID** | UC-008 |
| **Title** | Monitor Bed Availability |
| **Actors** | ACT-04 (Bed Manager) |
| **Trigger** | ADT event triggers bed status change; bed manager opens bed board |
| **Preconditions** | Bed management module accessible; at least one unit configured |
| **Mapped FRs** | FR-041, FR-043, FR-044 |

**Main Success Scenario:**

1. Bed Manager opens the Bed Board screen.
2. System displays all beds across all units with current status (Available, Occupied, Pending Discharge, Under Cleaning).
3. Discharge predictions are shown for occupied beds (ML-estimated time to available).
4. Status updates appear in real-time as ADT events are processed.
5. When ED boarding time exceeds the threshold, an alert badge appears and a notification is dispatched.

---

### UC-009 — Assign Bed to Incoming Patient

| Field | Detail |
|---|---|
| **Use Case ID** | UC-009 |
| **Title** | Assign Bed to Incoming Patient |
| **Actors** | ACT-04 (Bed Manager), ACT-09 (Bed Management Agent) |
| **Trigger** | New patient admission or transfer requires bed assignment |
| **Preconditions** | Patient acuity and isolation requirements known; bed board data current |
| **Mapped FRs** | FR-040, FR-041, FR-042 |

**Main Success Scenario:**

1. Bed Management Agent receives patient acuity, diagnosis category, and isolation requirements.
2. Agent queries real-time bed availability data.
3. Agent applies matching rules (acuity vs. unit capability, isolation, proximity to nursing station for high-risk patients).
4. Agent presents top 3 recommended beds with rationale to Bed Manager.
5. Bed Manager selects the assignment and confirms.
6. Bed status updated to Occupied; assigned nurse notified.

---

### UC-010 — Assess Readmission Risk

| Field | Detail |
|---|---|
| **Use Case ID** | UC-010 |
| **Title** | Assess Readmission Risk |
| **Actors** | ACT-01 (Floor Nurse), ACT-07 (Supervisor), ACT-09 (Follow-up Care Agent) |
| **Trigger** | Discharge event processed (UC-004) |
| **Preconditions** | Patient encounter data complete; ML model deployed |
| **Mapped FRs** | FR-052, FR-053 |

**Main Success Scenario:**

1. Follow-up Care Agent retrieves encounter features: diagnoses, length of stay, medication count, prior admissions, discharge destination, lab values.
2. Agent invokes the Scikit-learn readmission risk model.
3. Model returns a risk score between 0.0 and 1.0 with feature importance breakdown.
4. Risk score stored in the encounter record and displayed on the dashboard.
5. If score ≥ 0.7, agent triggers automatic follow-up scheduling (see UC-011).
6. Care manager is notified of all high-risk patients for active follow-up.

---

### UC-011 — Schedule Post-Discharge Follow-up

| Field | Detail |
|---|---|
| **Use Case ID** | UC-011 |
| **Title** | Schedule Post-Discharge Follow-up |
| **Actors** | ACT-05 (Patient), ACT-01 (Floor Nurse), ACT-09 (Follow-up Care Agent) |
| **Trigger** | High-risk patient discharged (risk score ≥ 0.7) or nurse initiates follow-up |
| **Preconditions** | Patient contact information present; provider availability accessible |
| **Mapped FRs** | FR-050, FR-051, FR-053 |

**Main Success Scenario:**

1. Follow-up Care Agent identifies the patient's primary care provider (PCP) or relevant specialist.
2. Agent checks provider availability and books the earliest appointment within 7 days.
3. Appointment confirmation sent to patient via SMS and/or email.
4. Appointment details recorded in the encounter record.
5. Medication reminder schedule configured for the post-discharge period.
6. Nurse notified of appointment booking confirmation.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 2a | No appointment available within 7 days | Nurse notified; manual scheduling task created |

---

### UC-012 — Patient Chatbot Interaction

| Field | Detail |
|---|---|
| **Use Case ID** | UC-012 |
| **Title** | Patient Chatbot Interaction |
| **Actors** | ACT-05 (Patient), ACT-09 (Patient Communication Agent) |
| **Trigger** | Patient opens the patient portal and initiates a chat session |
| **Preconditions** | Patient authenticated; discharge instructions exist for the encounter |
| **Mapped FRs** | FR-060, FR-061, FR-062, FR-063, FR-064 |

**Main Success Scenario:**

1. Patient logs into the patient portal and opens the chat widget.
2. Chatbot greets patient in their preferred language.
3. Patient submits a query (text or voice-to-text).
4. Patient Communication Agent retrieves the patient's encounter context (instructions, medications, appointments).
5. Agent queries Vertex AI LLM with the patient context and question.
6. LLM generates a contextual response within 3 seconds.
7. Response displayed to patient in preferred language.
8. Interaction logged for audit and quality review.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 3a | Patient submits urgency keywords (e.g., "chest pain", "can't breathe") | Escalation triggered; patient shown emergency contact instructions; on-call nurse alerted within 2 minutes |
| 6a | LLM confidence below threshold | Chatbot recommends the patient call the nurse line; escalation option presented |

---

### UC-013 — Escalate Patient Concern to Care Team

| Field | Detail |
|---|---|
| **Use Case ID** | UC-013 |
| **Title** | Escalate Patient Concern to Care Team |
| **Actors** | ACT-05 (Patient), ACT-01 (Floor Nurse), ACT-07 (Supervisor), ACT-09 (Patient Communication Agent) |
| **Trigger** | Patient submits an urgent query (UC-012 Extension 3a) or Follow-up Care Agent detects concern (FR-054) |
| **Preconditions** | Patient has an active post-discharge encounter record; care team assigned |
| **Mapped FRs** | FR-054, FR-055, FR-062 |

**Main Success Scenario:**

1. Agent classifies the concern as urgent based on keyword detection or symptom pattern.
2. Agent creates an escalation record with severity classification (Low / Medium / High / Critical).
3. Escalation alert sent to the assigned nurse via dashboard and SMS within 5 minutes.
4. Patient notified that a care team member will contact them.
5. Nurse acknowledges the escalation on the dashboard within 30 minutes.
6. Nurse records resolution action in the escalation record.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 5a | Escalation not acknowledged within 30 minutes | Supervisor alert sent automatically |

---

### UC-014 — Review and Approve AI-Generated Document

| Field | Detail |
|---|---|
| **Use Case ID** | UC-014 |
| **Title** | Review and Approve AI-Generated Document |
| **Actors** | ACT-02 (Attending Physician), ACT-01 (Floor Nurse), ACT-09 (Documentation Agent) |
| **Trigger** | Documentation Agent completes a document draft |
| **Preconditions** | AI-generated document exists in Draft status |
| **Mapped FRs** | FR-024, FR-025 |

**Main Success Scenario:**

1. Clinician receives in-app notification of a document pending review.
2. Clinician opens the document review screen.
3. Document is displayed with "AI-Assisted" label and AI-generated sections highlighted.
4. Clinician reads the document and makes inline edits as needed.
5. Clinician approves the document; status changes to Finalized.
6. Document metadata records the reviewer's identity, role, and approval timestamp.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 4a | Clinician rejects the document | Rejection reason entered; document returns to Documentation Agent for revision |

---

### UC-015 — View Care Team Dashboard

| Field | Detail |
|---|---|
| **Use Case ID** | UC-015 |
| **Title** | View Care Team Dashboard |
| **Actors** | ACT-01 (Floor Nurse), ACT-02 (Attending Physician), ACT-03 (Clinical Pharmacist), ACT-04 (Bed Manager), ACT-07 (Supervisor) |
| **Trigger** | Staff member logs into SmartHandoff |
| **Preconditions** | User authenticated with valid role |
| **Mapped FRs** | FR-070, FR-071, FR-072, FR-074, FR-080, FR-081 |

**Main Success Scenario:**

1. User authenticates and is directed to the dashboard home.
2. System renders the role-specific dashboard layout within 2 seconds.
3. Dashboard displays: real-time ADT event feed, patient list with risk scores, agent task status, pending actions, and relevant alerts.
4. User selects a patient from the list to view the Patient Detail screen.
5. Patient Detail screen shows demographics, medications, active tasks, generated documents, and risk score.
6. Real-time updates (new ADT events, task completions, alerts) appear without page refresh.

---

### UC-016 — Monitor AI Agent Activity

| Field | Detail |
|---|---|
| **Use Case ID** | UC-016 |
| **Title** | Monitor AI Agent Activity |
| **Actors** | ACT-07 (Supervisor), ACT-06 (IT Administrator) |
| **Trigger** | Supervisor/Admin navigates to the Agent Monitor screen |
| **Preconditions** | User has Supervisor or Admin role |
| **Mapped FRs** | FR-072 |

**Main Success Scenario:**

1. User opens the Agent Monitor screen.
2. System displays all active agent tasks with status: Agent type, patient encounter, task status (Pending / In Progress / Completed / Failed), start time, duration.
3. Failed tasks are highlighted in red with error detail visible on hover/click.
4. Supervisor can trigger a manual retry for failed tasks.
5. Task history is filterable by agent type, date range, and status.

---

### UC-017 — Access Patient Portal

| Field | Detail |
|---|---|
| **Use Case ID** | UC-017 |
| **Title** | Access Patient Portal |
| **Actors** | ACT-05 (Patient) |
| **Trigger** | Patient follows the portal link from their discharge communication |
| **Preconditions** | Patient has received portal access credentials; encounter is linked |
| **Mapped FRs** | FR-060, FR-061, FR-064 |

**Main Success Scenario:**

1. Patient opens the portal URL on a mobile or desktop browser.
2. Patient authenticates (secure token from discharge communication or OTP).
3. Patient portal home displays: discharge instructions, medication list, follow-up appointment details, and chat widget.
4. Patient can download or print their instructions.
5. Patient initiates a chat session (see UC-012).

---

### UC-018 — View Analytics & KPI Dashboard

| Field | Detail |
|---|---|
| **Use Case ID** | UC-018 |
| **Title** | View Analytics & KPI Dashboard |
| **Actors** | ACT-07 (Supervisor / Manager) |
| **Trigger** | Manager navigates to the Analytics screen |
| **Preconditions** | User has Manager or Admin role |
| **Mapped FRs** | FR-073 |

**Main Success Scenario:**

1. Manager opens the Analytics screen.
2. System loads KPI dashboard with default view: current month.
3. KPIs displayed: average discharge documentation time, 30-day readmission rate, medication reconciliation completion rate, ED boarding time, agent task success rate, patient satisfaction score.
4. Manager applies date range and unit filters.
5. KPIs recalculate and charts refresh within 2 seconds of filter change.
6. Manager can export the report as CSV or PDF.

---

### UC-019 — Authenticate and Manage User Session

| Field | Detail |
|---|---|
| **Use Case ID** | UC-019 |
| **Title** | Authenticate and Manage User Session |
| **Actors** | ACT-01–ACT-07 (all staff users) |
| **Trigger** | User navigates to SmartHandoff URL |
| **Preconditions** | Hospital SSO configured and reachable |
| **Mapped FRs** | FR-085, FR-086, FR-087, FR-088 |

**Main Success Scenario:**

1. User navigates to SmartHandoff URL; system redirects to hospital SSO login.
2. User enters credentials; SSO validates identity.
3. MFA challenge presented; user completes MFA.
4. SSO issues OIDC ID token; SmartHandoff exchanges it for a session JWT.
5. System loads user's RBAC role from the identity provider claims.
6. User is directed to their role-specific dashboard.
7. After 30 minutes of inactivity, session is invalidated and user is redirected to login.

**Extensions:**

| Step | Condition | Handling |
|---|---|---|
| 2a | SSO unreachable | Error message displayed; IT contact displayed |
| 3a | MFA fails 3 consecutive times | Account locked for 15 minutes; IT notified |

---

### UC-020 — Administer System Configuration

| Field | Detail |
|---|---|
| **Use Case ID** | UC-020 |
| **Title** | Administer System Configuration |
| **Actors** | ACT-06 (IT Administrator) |
| **Trigger** | Admin opens the Admin Settings screen |
| **Preconditions** | User authenticated with IT Admin role |
| **Mapped FRs** | FR-074, FR-087 |

**Main Success Scenario:**

1. Admin opens the Admin Settings screen.
2. Admin views and manages: user accounts and roles, notification thresholds, ED boarding alert threshold, supported languages, agent configuration parameters.
3. Admin makes a configuration change; change is logged in the audit trail.
4. Configuration changes take effect within 60 seconds without requiring system restart.

---

## 6. Business Rules

The following business rules constrain system behaviour and must be enforced in implementation.

| Rule ID | Business Rule | Enforcement Point |
|---|---|---|
| BR-001 | All discharge summaries must be reviewed and approved by a licensed clinician before finalization. | Documentation Agent; document status gate |
| BR-002 | Medication reconciliation must be completed within 24 hours of admission. | Follow-up Care Agent; SLA monitor |
| BR-003 | Patients with readmission risk score ≥ 0.7 must have a follow-up appointment scheduled within 7 days of discharge. | Follow-up Care Agent; automatic booking |
| BR-004 | Discharge instructions must be provided in the patient's preferred language. | Documentation Agent; patient preference lookup |
| BR-005 | Critical drug-drug interactions must generate an immediate alert to the responsible pharmacist. | Medication Reconciliation Agent; real-time alert |
| BR-006 | ADT events must be processed within 5 seconds of receipt. | API gateway; SLA monitoring |
| BR-007 | All AI-generated content must be clearly labelled "AI-Assisted" in both the UI and document metadata. | Documentation Agent; all AI agent outputs |
| BR-008 | All access to Protected Health Information (PHI) must be logged in an immutable audit trail. | API middleware; data access layer |
| BR-009 | User sessions must time out after 30 minutes of inactivity. | Session management middleware |
| BR-010 | Escalations not addressed within 30 minutes must automatically notify the supervisor. | Follow-up Care Agent; escalation monitor |
| BR-011 | Patient identifiers must be encrypted at rest (AES-256) and in transit (TLS 1.3). | Data layer; network configuration |
| BR-012 | PHI must not be written to application logs. | Logging middleware; log scrubbing |
| BR-013 | Active patient records retained for 7 years; audit logs retained for 6 years. | Data retention policy; automated archival |

---

## 7. Data Requirements

### Core Entities

| Entity | Key Attributes | Source | Sensitivity |
|---|---|---|---|
| **Patient** | PatientId, MRN, Name, DOB, Gender, LanguagePreference, Phone, Email | EHR / FHIR | PHI — High |
| **Encounter** | EncounterId, PatientId, AdmitDate, DischargeDate, Unit, AttendingMD, Status, RiskScore | EHR / FHIR | PHI — High |
| **ADTEvent** | EventId, EncounterId, EventType, EventTime, SourceSystem, ProcessedTime, AgentTriggered | System Generated | PHI — Medium |
| **Medication** | MedicationId, EncounterId, DrugName, RxNormCode, Dosage, Frequency, Route, Status, ConflictFlag | EHR / FHIR | PHI — High |
| **AgentTask** | TaskId, EncounterId, AgentType, Status, StartTime, EndTime, Result, ErrorMessage | System Generated | Internal |
| **Document** | DocumentId, EncounterId, DocumentType, Content, GeneratedBy, ReviewedBy, Status, CreatedAt | System Generated | PHI — High |
| **AuditLog** | LogId, UserId, PatientId, Action, ResourceType, ResourceId, Timestamp, IPAddress | System Generated | PHI — High |
| **User** | UserId, Name, Role, Email, UnitAssignment | Identity Provider | Internal |

### Data Quality Rules

| Rule | Description |
|---|---|
| **Completeness** | MRN, EventType, EventTime, EncounterId required on all ADT events; null rejection enforced |
| **Uniqueness** | MRN unique per patient; deduplication via MRN-matching algorithm |
| **Accuracy** | Medication RxNorm codes validated against RXNORM vocabulary on ingest |
| **Timeliness** | FHIR data refresh latency ≤ 60 seconds; ADT event processing ≤ 5 seconds |
| **Integrity** | Foreign key relationships enforced at DB level; orphan record cleanup job scheduled daily |
| **PHI Protection** | PHI fields encrypted at rest; PHI excluded from all log records |

---

## 8. Acceptance Criteria

### Feature-Level Acceptance

| Feature Area | Acceptance Criteria |
|---|---|
| **ADT Processing** | All 8 event types (A01–A13) processed within 5 seconds; 100% audit coverage; duplicates rejected |
| **Documentation Agent** | Discharge summary generated within 30 seconds; readability score ≥ 60; 5 languages available; AI label present |
| **Medication Reconciliation** | Drug interaction detection sensitivity ≥ 99%; reconciliation completed within 24 hours of admission; pharmacist alert ≤ 60 seconds |
| **Bed Management** | Bed board updates within 5 seconds of ADT event; ED boarding alert delivered within 1 minute of threshold breach |
| **Follow-up Care** | Risk score computed within 60 seconds of discharge; high-risk follow-up booked within 5 minutes |
| **Patient Communication** | Chatbot response ≤ 3 seconds (p95); urgent escalation ≤ 2 minutes; 24/7 availability |
| **Dashboard** | Page load ≤ 2 seconds; real-time updates visible; all KPIs accurate; role-based views enforced |
| **Authentication** | SSO + MFA login functional; session timeout at 30 minutes; RBAC enforced at API layer |

### System-Level Acceptance

| Category | Criterion |
|---|---|
| **Performance** | 95th-percentile API response time ≤ 500ms; page load ≤ 2 seconds |
| **Scalability** | System handles 500 concurrent users and 5,000 ADT events/day without degradation |
| **Availability** | 99.9% uptime over any rolling 30-day period |
| **Security** | Pass third-party security assessment; zero critical OWASP findings |
| **Usability** | ≥ 80% user satisfaction in UAT survey; user error rate ≤ 5% |
| **Accessibility** | WCAG 2.1 AA compliance verified by automated and manual audit |
| **Data Integrity** | Zero patient data loss; backup recovery verified within RPO of 15 minutes |

---

## 9. Traceability Matrix

| UC ID | Title | Mapped FR IDs |
|---|---|---|
| UC-001 | Receive and Route ADT Event | FR-001, FR-002, FR-003, FR-004, FR-005, FR-006 |
| UC-002 | Orchestrate Patient Admission | FR-003, FR-010, FR-013, FR-030, FR-036, FR-041, FR-052 |
| UC-003 | Orchestrate Patient Transfer | FR-003, FR-010, FR-011, FR-012, FR-013, FR-041, FR-042 |
| UC-004 | Orchestrate Patient Discharge | FR-003, FR-010, FR-020, FR-021, FR-023, FR-030, FR-052, FR-053 |
| UC-005 | Generate Discharge Summary | FR-020, FR-024, FR-025 |
| UC-006 | Generate Patient Discharge Instructions | FR-021, FR-022, FR-024, FR-025, FR-064 |
| UC-007 | Perform Medication Reconciliation | FR-030, FR-031, FR-032, FR-033, FR-034, FR-035, FR-036 |
| UC-008 | Monitor Bed Availability | FR-041, FR-043, FR-044 |
| UC-009 | Assign Bed to Incoming Patient | FR-040, FR-041, FR-042 |
| UC-010 | Assess Readmission Risk | FR-052, FR-053 |
| UC-011 | Schedule Post-Discharge Follow-up | FR-050, FR-051, FR-053 |
| UC-012 | Patient Chatbot Interaction | FR-060, FR-061, FR-062, FR-063, FR-064 |
| UC-013 | Escalate Patient Concern to Care Team | FR-054, FR-055, FR-062 |
| UC-014 | Review and Approve AI-Generated Document | FR-024, FR-025 |
| UC-015 | View Care Team Dashboard | FR-070, FR-071, FR-072, FR-074, FR-080, FR-081 |
| UC-016 | Monitor AI Agent Activity | FR-072 |
| UC-017 | Access Patient Portal | FR-060, FR-061, FR-064 |
| UC-018 | View Analytics & KPI Dashboard | FR-073 |
| UC-019 | Authenticate and Manage User Session | FR-085, FR-086, FR-087, FR-088 |
| UC-020 | Administer System Configuration | FR-074, FR-087 |

---

## Document Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-07-10 | SmartHandoff Project Team | Initial spec derived from BRD v1.0 |

---

*End of Specification*
