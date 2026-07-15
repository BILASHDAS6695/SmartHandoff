# SmartHandoff — Visual Design Model

> **Artifact:** model | **Version:** 1.0 | **Status:** Draft
> **Date:** 2026-07-13 | **Upstream:** SRS v1.0, Design v1.0 | **Workflow:** /design-model
> **Architect:** SmartHandoff Project Team

---

## Table of Contents

1. [C4 Context Diagram — System Context](#1-c4-context-diagram--system-context)
2. [C4 Container Diagram — System Containers](#2-c4-container-diagram--system-containers)
3. [C4 Component Diagram — AI Agent Subsystem](#3-c4-component-diagram--ai-agent-subsystem)
4. [Entity-Relationship Diagram (ERD)](#4-entity-relationship-diagram-erd)
5. [Encounter State Machine](#5-encounter-state-machine)
6. [Data Flow — ADT Event Pipeline](#6-data-flow--adt-event-pipeline)
7. [Sequence Diagram — Patient Discharge (UC-003)](#7-sequence-diagram--patient-discharge-uc-003)
8. [Sequence Diagram — Medication Reconciliation (UC-005)](#8-sequence-diagram--medication-reconciliation-uc-005)
9. [Sequence Diagram — Patient Chatbot (UC-008)](#9-sequence-diagram--patient-chatbot-uc-008)
10. [Sequence Diagram — Staff Authentication (UC-010)](#10-sequence-diagram--staff-authentication-uc-010)
11. [Deployment Diagram — GCP Infrastructure](#11-deployment-diagram--gcp-infrastructure)
12. [Class Diagram — Domain Model](#12-class-diagram--domain-model)

---

## 1. C4 Context Diagram — System Context

> **Level 1** · Who uses SmartHandoff and what external systems does it depend on?

```mermaid
C4Context
  title SmartHandoff — System Context (C4 Level 1)

  Person(nurse, "Floor Nurse", "Views patient status, completes handoff tasks, manages care transitions")
  Person(physician, "Attending Physician", "Reviews AI-generated summaries, approves discharges")
  Person(pharmacist, "Clinical Pharmacist", "Reconciles medications, resolves drug interaction alerts")
  Person(bedmgr, "Bed Manager", "Monitors bed board, manages patient flow and ED boarding")
  Person(patient, "Discharged Patient", "Views discharge instructions, asks questions via chatbot")
  Person(admin, "IT Admin", "Manages user accounts, monitors system health")

  System(smarthandoff, "SmartHandoff", "AI-powered care transition orchestrator. Automates ADT workflows via six specialised AI agents. Angular 17 PWA + Python FastAPI + LangChain.")

  System_Ext(ehr, "EHR System", "Hospital Electronic Health Record. Emits HL7 ADT messages via MLLP. Exposes FHIR R4 REST API for patient data.")
  System_Ext(idp, "Identity Provider", "Hospital SSO. OAuth 2.0 / OIDC with MFA. SCIM 2.0 user provisioning.")
  System_Ext(vertexai, "Vertex AI (Gemini)", "Google Cloud LLM platform. Powers document generation and patient chatbot.")
  System_Ext(twilio, "Twilio", "SMS delivery for medication reminders, patient OTP, and post-discharge check-ins.")
  System_Ext(sendgrid, "SendGrid", "Transactional email for patient portal links, appointment confirmations, and alerts.")
  System_Ext(rxnav, "RxNav / OpenFDA", "NIH drug interaction database. Used by Medication Reconciliation Agent.")

  Rel(nurse, smarthandoff, "Uses", "HTTPS / Angular PWA")
  Rel(physician, smarthandoff, "Uses", "HTTPS / Angular PWA")
  Rel(pharmacist, smarthandoff, "Uses", "HTTPS / Angular PWA")
  Rel(bedmgr, smarthandoff, "Uses", "HTTPS / Angular PWA")
  Rel(patient, smarthandoff, "Uses", "HTTPS / Mobile Browser (PWA)")
  Rel(admin, smarthandoff, "Manages", "HTTPS / Admin Settings")

  Rel(ehr, smarthandoff, "Sends ADT events", "HL7 v2.x MLLP / TCP 2575")
  Rel(smarthandoff, ehr, "Reads patient data", "FHIR R4 REST / HTTPS (read-only)")
  Rel(smarthandoff, idp, "Authenticates via", "OIDC / OAuth 2.0 + MFA")
  Rel(smarthandoff, vertexai, "Generates documents and chatbot responses via", "REST / HTTPS")
  Rel(smarthandoff, twilio, "Sends SMS reminders and OTP via", "REST / HTTPS")
  Rel(smarthandoff, sendgrid, "Sends emails via", "REST / HTTPS")
  Rel(smarthandoff, rxnav, "Checks drug interactions via", "REST / HTTPS")

  UpdateLayoutConfig($c4ShapeInRow="4", $c4BoundaryInRow="1")
```

---

## 2. C4 Container Diagram — System Containers

> **Level 2** · What are the deployable containers within SmartHandoff?

```mermaid
C4Container
  title SmartHandoff — Container Diagram (C4 Level 2)

  Person(staff, "Hospital Staff", "Nurses, Physicians, Pharmacists, Bed Managers")
  Person(patient, "Patient", "Post-discharge, mobile browser")

  System_Ext(ehr, "EHR System", "HL7 ADT + FHIR R4")
  System_Ext(idp, "Identity Provider", "OIDC / SCIM")
  System_Ext(vertexai, "Vertex AI", "Gemini LLM")
  System_Ext(notifications, "Twilio / SendGrid", "SMS + Email")
  System_Ext(rxnav, "RxNav / OpenFDA", "Drug Interactions")

  System_Boundary(sh, "SmartHandoff — GCP us-central1") {

    Container(pwa, "Angular 17 PWA", "TypeScript / Angular 17", "Staff dashboard with real-time ADT feed, bed board, medication queue, document review. Patient portal with discharge instructions and chatbot. Served from Cloud CDN.")

    Container(api, "FastAPI Backend", "Python 3.12 / FastAPI", "REST API + SignalR WebSocket hub. JWT auth, RBAC enforcement, PHI audit logging. Reads from Cloud SQL replica for dashboards; writes to primary for commands.")

    Container(hl7, "HL7 Listener", "Python / hl7apy", "MLLP TCP listener on port 2575. Parses HL7 v2.x ADT messages, archives raw messages to Cloud Storage, publishes parsed events to Pub/Sub.")

    Container(pubsub, "GCP Pub/Sub", "Managed Messaging", "adt-events topic with per-agent subscriptions. Dead-letter queues per subscription. Decouples HL7 intake from agent processing.")

    Container(coordinator, "Transition Coordinator Agent", "Python / LangChain", "Orchestrates workflows across all agents on ADT event receipt. Tracks task completion, escalates SLA breaches, pushes status via SignalR.")

    Container(docagent, "Documentation Agent", "Python / LangChain + Vertex AI", "Generates discharge summaries and patient instructions (30s SLA). Completeness checks. Multilingual output. Human review workflow.")

    Container(medagent, "Medication Reconciliation Agent", "Python / LangChain + RxNav", "Compares pre-admission / inpatient / discharge medication lists. Detects interactions, duplicates, missing chronic meds. Pharmacist alerts.")

    Container(bedagent, "Bed Management Agent", "Python / Scikit-learn", "Real-time bed board. Discharge time prediction (ML). Bed assignment scoring. ED boarding alerts.")

    Container(followupagent, "Follow-up Care Agent", "Python / LangChain + Scikit-learn", "Readmission risk scoring (ML). Follow-up appointment scheduling. Medication reminder dispatch. High-risk patient pathway.")

    Container(commsagent, "Patient Communication Agent", "Python / LangChain + Vertex AI", "24/7 patient chatbot (Gemini Flash). Urgency signal detection. Escalation routing. Transcript storage.")

    Container(mlinference, "ML Inference Service", "Python / FastAPI + Scikit-learn", "REST endpoint serving readmission risk model and LOS discharge prediction model.")

    Container(notifysvc, "Notification Service", "Python", "Dispatches SMS (Twilio) and email (SendGrid) from notification-requests Pub/Sub topic. Idempotent delivery with retry.")

    Container(db_primary, "Cloud SQL Primary", "PostgreSQL 15 / CMEK", "ACID transactional writes. PHI field-level AES-256-GCM encryption. Append-only audit_log table. WAL enabled.")

    Container(db_replica, "Cloud SQL Replica", "PostgreSQL 15", "Read-only replica. Materialised views: mv_bed_board (60s), mv_risk_dashboard (5min), mv_kpi_daily (nightly).")

    Container(redis, "Cloud Memorystore", "Redis 7", "Token blocklist for revoked JWTs. Drug interaction result cache (24h TTL). Bed board cache.")

    Container(storage, "Cloud Storage", "GCP Managed", "HIPAA CMEK bucket: raw HL7 archive, audit log WORM export, ML model artifacts. Angular PWA static assets (CDN-served).")
  }

  Rel(staff, pwa, "Uses", "HTTPS")
  Rel(patient, pwa, "Uses", "HTTPS / Mobile Browser")
  Rel(pwa, api, "REST + WebSocket", "HTTPS / SignalR")

  Rel(ehr, hl7, "Sends ADT events", "HL7 v2.x MLLP")
  Rel(hl7, pubsub, "Publishes ADT events", "gRPC")
  Rel(hl7, storage, "Archives raw HL7", "HTTPS")
  Rel(api, ehr, "Reads patient data", "FHIR R4 REST")
  Rel(api, idp, "Validates tokens via", "OIDC JWKS")
  Rel(api, db_primary, "Writes commands to", "TCP / PostgreSQL")
  Rel(api, db_replica, "Reads queries from", "TCP / PostgreSQL")
  Rel(api, redis, "Token blocklist, caches", "Redis protocol")

  Rel(pubsub, coordinator, "Delivers ADT events", "Pub/Sub pull")
  Rel(pubsub, docagent, "Delivers ADT events", "Pub/Sub pull")
  Rel(pubsub, medagent, "Delivers ADT events", "Pub/Sub pull")
  Rel(pubsub, bedagent, "Delivers ADT events", "Pub/Sub pull")
  Rel(pubsub, followupagent, "Delivers ADT events", "Pub/Sub pull")
  Rel(pubsub, commsagent, "Delivers discharge events", "Pub/Sub pull")

  Rel(coordinator, api, "Updates task status via", "REST / SignalR")
  Rel(docagent, vertexai, "Generates documents via", "REST / HTTPS")
  Rel(commsagent, vertexai, "Chatbot responses via", "REST / HTTPS")
  Rel(medagent, rxnav, "Drug interaction checks via", "REST / HTTPS")
  Rel(followupagent, mlinference, "Risk score requests to", "REST / HTTPS")
  Rel(bedagent, mlinference, "LOS predictions from", "REST / HTTPS")

  Rel(followupagent, pubsub, "Publishes notification requests", "gRPC")
  Rel(notifysvc, notifications, "Sends SMS/email via", "REST / HTTPS")

  Rel(coordinator, db_primary, "Writes agent tasks", "TCP")
  Rel(docagent, db_primary, "Writes documents", "TCP")
  Rel(medagent, db_primary, "Writes reconciliation records", "TCP")
  Rel(bedagent, db_primary, "Updates bed status", "TCP")

  UpdateLayoutConfig($c4ShapeInRow="4", $c4BoundaryInRow="2")
```

---

## 3. C4 Component Diagram — AI Agent Subsystem

> **Level 3** · Internal components of the AI Agent subsystem (Documentation Agent shown as representative)

```mermaid
C4Component
  title Documentation Agent — Component Diagram (C4 Level 3)

  Container_Ext(pubsub, "GCP Pub/Sub", "docs-agent-sub subscription")
  Container_Ext(vertexai, "Vertex AI Gemini 1.5 Pro", "LLM API")
  Container_Ext(fhir, "FHIR R4 API", "EHR Patient Data")
  Container_Ext(db, "Cloud SQL Primary", "Document + AgentTask tables")
  Container_Ext(api, "FastAPI Backend", "SignalR hub + REST")

  Container_Boundary(docagent, "Documentation Agent — Cloud Run Service") {

    Component(consumer, "Pub/Sub Consumer", "Python asyncio", "Pulls messages from docs-agent-sub. Validates message schema. Sends ACK on success or NACK on transient failure. Implements idempotency check via source_message_id.")

    Component(orchestrator, "LangChain Orchestrator", "LangChain AgentExecutor", "Manages tool invocation sequence. Enforces 25-second LLM timeout. Falls back to template generation on timeout or LLM error.")

    Component(fhirfetcher, "FHIR Data Fetcher", "Python / fhir.resources + httpx", "Fetches Patient, Encounter, Condition, MedicationStatement from FHIR R4. Applies circuit breaker (10 failures / 60s). Implements exponential backoff retry.")

    Component(promptbuilder, "Prompt Builder", "Python / Jinja2 templates", "Constructs structured LLM prompts from patient context. Enforces minimum-necessary PHI principle. Injects encounter data, diagnosis codes, and template schema.")

    Component(llmclient, "Vertex AI Client", "Python / google-cloud-aiplatform", "Calls Gemini 1.5 Pro with response_mime_type=application/json. Streams response tokens. Validates output against Pydantic discharge summary schema.")

    Component(completeness, "Completeness Validator", "Python / Pydantic", "Checks generated document against required-fields checklist (diagnosis, medications, follow-up, warnings). Returns list of missing fields. Blocks ready-for-review transition if incomplete.")

    Component(translator, "Language Translator", "Python / LangChain", "Translates patient instructions to preferred language (es/fr/zh/pt). Stores bilingual pair. Quality check: back-translation delta < 15% semantic distance.")

    Component(docwriter, "Document Writer", "Python / SQLAlchemy", "Persists Document record with status=DRAFT, generation_type, and AI-Assisted label. Encrypts content field via AES-256-GCM TypeDecorator.")

    Component(notifier, "Task Notifier", "Python / httpx", "Writes AgentTask completion record to DB. POSTs status update to FastAPI SignalR hub endpoint. Triggers dashboard real-time push.")
  }

  Rel(pubsub, consumer, "Delivers ADT A03 event", "Pub/Sub pull")
  Rel(consumer, orchestrator, "Triggers workflow", "Method call")
  Rel(orchestrator, fhirfetcher, "Fetches patient context", "Tool call")
  Rel(fhirfetcher, fhir, "FHIR resource GET", "HTTPS")
  Rel(orchestrator, promptbuilder, "Builds prompt", "Tool call")
  Rel(orchestrator, llmclient, "Generates summary", "Tool call")
  Rel(llmclient, vertexai, "Gemini API call", "HTTPS / streaming")
  Rel(orchestrator, completeness, "Validates completeness", "Tool call")
  Rel(orchestrator, translator, "Translates instructions", "Tool call")
  Rel(orchestrator, docwriter, "Persists document", "Tool call")
  Rel(docwriter, db, "INSERT document", "TCP / SQLAlchemy")
  Rel(orchestrator, notifier, "Notifies completion", "Tool call")
  Rel(notifier, db, "UPDATE agent_task", "TCP / SQLAlchemy")
  Rel(notifier, api, "POST /hubs/dashboard/notify", "REST / HTTPS")
  Rel(api, db, "SignalR push → staff browser", "WebSocket")
```

---

## 4. Entity-Relationship Diagram (ERD)

> **Database schema** · Core domain entities with cardinalities and PHI annotations

```mermaid
erDiagram
    PATIENT {
        uuid patient_id PK
        varchar mrn UK "deterministic AES-256-GCM"
        varchar first_name "AES-256-GCM encrypted"
        varchar last_name "AES-256-GCM encrypted"
        date dob "AES-256-GCM encrypted"
        varchar gender
        varchar language "ISO 639-1 code"
        varchar phone "AES-256-GCM encrypted"
        varchar email "AES-256-GCM encrypted"
        timestamp created_at
        timestamp deleted_at "soft delete"
    }

    ENCOUNTER {
        uuid encounter_id PK
        uuid patient_id FK
        timestamp admit_date
        timestamp discharge_date
        varchar unit
        varchar attending_md
        varchar status "REGISTERED|ADMITTED|TRANSFERRED|DISCHARGED|CANCELLED"
        decimal risk_score "0.0-1.0 readmission risk"
        varchar risk_tier "LOW|MEDIUM|HIGH"
        timestamp created_at
        timestamp deleted_at "soft delete"
    }

    ADT_EVENT {
        uuid event_id PK
        uuid encounter_id FK
        varchar event_type "A01|A02|A03|A04|A08|A11|A12|A13"
        timestamp event_time
        varchar source_system
        varchar source_message_id UK "MSH-10 idempotency key"
        timestamp processed_time
        varchar processing_status "RECEIVED|PROCESSING|COMPLETE|FAILED|CANCELLED"
        boolean agent_triggered
        text error_message
    }

    MEDICATION {
        uuid medication_id PK
        uuid encounter_id FK
        varchar drug_name
        varchar rxcui "RxNorm concept unique identifier"
        varchar dosage
        varchar frequency
        varchar route
        varchar list_type "PRE_ADMISSION|INPATIENT|DISCHARGE"
        varchar status "CONTINUED|NEW|STOPPED|DOSE_CHANGED"
        boolean conflict_flag
        varchar interaction_severity "NONE|LOW|MEDIUM|HIGH"
        boolean duplicate_flag
        timestamp created_at
    }

    AGENT_TASK {
        uuid task_id PK
        uuid encounter_id FK
        varchar agent_type "COORDINATOR|DOCUMENTATION|MED_RECON|BED_MGMT|FOLLOWUP|COMMS"
        varchar status "PENDING|IN_PROGRESS|COMPLETE|FAILED|CANCELLED"
        timestamp start_time
        timestamp end_time
        integer duration_ms
        jsonb result "structured agent output"
        text error_message
        integer retry_count
        timestamp created_at
    }

    DOCUMENT {
        uuid document_id PK
        uuid encounter_id FK
        varchar document_type "DISCHARGE_SUMMARY|PATIENT_INSTRUCTIONS|TRANSFER_NOTE|MED_SUMMARY"
        text content "AES-256-GCM encrypted"
        varchar language "ISO 639-1 code"
        varchar generation_type "AI_GENERATED|TEMPLATE|HUMAN"
        uuid generated_by_task_id FK
        uuid reviewed_by_user_id FK
        timestamp approved_at
        varchar status "DRAFT|PENDING_REVIEW|APPROVED|REJECTED"
        boolean ai_assisted_label
        timestamp created_at
    }

    BED {
        uuid bed_id PK
        varchar unit
        varchar room
        varchar bed_label
        varchar bed_type "GENERAL|ICU|ISOLATION|STEP_DOWN"
        varchar status "CLEAN|DIRTY|OCCUPIED|BLOCKED|MAINTENANCE"
        uuid current_encounter_id FK
        timestamp predicted_discharge_at
        timestamp last_updated
    }

    AUDIT_LOG {
        uuid audit_id PK
        uuid user_id FK
        varchar user_role
        varchar action "READ|WRITE|APPROVE|LOGIN|LOGOUT|EXPORT"
        varchar entity_type "PATIENT|ENCOUNTER|DOCUMENT|MEDICATION|BED"
        uuid entity_id
        varchar ip_address
        varchar user_agent
        timestamp action_at
        jsonb metadata "non-PHI contextual data only"
    }

    APP_USER {
        uuid user_id PK
        varchar email UK
        varchar role "ADMIN|PHYSICIAN|NURSE|PHARMACIST|BED_MANAGER|READ_ONLY"
        varchar idp_subject UK "SSO subject identifier"
        boolean active
        timestamp last_login
        timestamp created_at
        timestamp deprovisioned_at
    }

    CHATBOT_TRANSCRIPT {
        uuid transcript_id PK
        uuid encounter_id FK
        varchar direction "PATIENT|AGENT"
        text message "AES-256-GCM encrypted"
        boolean urgency_flag
        boolean escalated
        uuid escalated_to_user_id FK
        timestamp sent_at
    }

    PATIENT ||--o{ ENCOUNTER : "has"
    ENCOUNTER ||--o{ ADT_EVENT : "triggers"
    ENCOUNTER ||--o{ MEDICATION : "has"
    ENCOUNTER ||--o{ AGENT_TASK : "generates"
    ENCOUNTER ||--o{ DOCUMENT : "produces"
    ENCOUNTER ||--o| BED : "occupies"
    ENCOUNTER ||--o{ CHATBOT_TRANSCRIPT : "has"
    AGENT_TASK ||--o{ DOCUMENT : "generates"
    APP_USER ||--o{ AUDIT_LOG : "creates"
    APP_USER ||--o{ DOCUMENT : "reviews"
```

---

## 5. Encounter State Machine

> **State transitions** · Lifecycle of an Encounter from ADT event to close

```mermaid
stateDiagram-v2
  [*] --> REGISTERED : ADT A04 (Register Patient)

  REGISTERED --> ADMITTED : ADT A01 (Admit)
  REGISTERED --> CANCELLED : ADT A11 (Cancel Register)

  ADMITTED --> TRANSFERRED : ADT A02 (Transfer)
  ADMITTED --> DISCHARGED : ADT A03 (Discharge)
  ADMITTED --> CANCELLED : ADT A11 (Cancel Admit)

  TRANSFERRED --> TRANSFERRED : ADT A02 (Transfer again)
  TRANSFERRED --> DISCHARGED : ADT A03 (Discharge)
  TRANSFERRED --> ADMITTED : ADT A12 (Cancel Transfer → revert)
  TRANSFERRED --> CANCELLED : ADT A11 (Cancel Admit)

  DISCHARGED --> ADMITTED : ADT A13 (Cancel Discharge → revert)

  DISCHARGED --> ARCHIVED : pg_cron job after 7 years

  CANCELLED --> [*]
  ARCHIVED --> [*]

  note right of ADMITTED
    Triggers on ADMITTED:
    ─ Coordinator Agent workflow
    ─ Medication Reconciliation (24h window)
    ─ Bed assignment
    ─ Risk assessment initialised
  end note

  note right of TRANSFERRED
    Triggers on TRANSFERRED:
    ─ Transfer handoff checklist
    ─ Transfer note generated
    ─ Bed board updated (src → dirty, dst → occupied)
  end note

  note right of DISCHARGED
    Triggers on DISCHARGED:
    ─ Discharge summary generated (≤30s)
    ─ Medication change summary
    ─ Final readmission risk score
    ─ Follow-up appointment scheduled
    ─ Patient portal activated
    ─ Bed marked dirty / housekeeping notified
    ─ Chatbot window opened (30 days)
  end note
```

---

## 6. Data Flow — ADT Event Pipeline

> **Data flow** · End-to-end journey from HL7 message receipt to agent execution and dashboard update

```mermaid
flowchart TD
    EHR([🏥 EHR System]) -->|HL7 ADT message\nMLLP / TCP 2575| MLLP[HL7 Listener\nCloud Run]

    MLLP -->|Raw .hl7 file\nbefore ACK| STORAGE[(Cloud Storage\nHIPAA CMEK Bucket)]
    MLLP -->|ACK AA within 200ms\nor NACK AE on parse error| EHR

    MLLP -->|Parse MSH, EVN, PID, PV1\nMap to ADTEvent domain model| VALIDATE{Valid\nMessage?}

    VALIDATE -->|No| DLQ_MLLP[(MLLP Error Log\n+ Alert)]
    VALIDATE -->|Yes| PUBSUB[GCP Pub/Sub\nadt-events topic]

    PUBSUB -->|coordinator-sub| COORD[Transition Coordinator\nAgent]
    PUBSUB -->|docs-agent-sub| DOCAGT[Documentation\nAgent]
    PUBSUB -->|medrecon-sub| MEDAGT[Medication Recon\nAgent]
    PUBSUB -->|bed-mgmt-sub| BEDAGT[Bed Management\nAgent]
    PUBSUB -->|followup-sub| FUPAGT[Follow-up Care\nAgent]
    PUBSUB -->|comms-sub| COMMSAGT[Patient Comms\nAgent]

    COORD -->|Create Encounter\nDispatch tasks| DB_W[(Cloud SQL\nPrimary)]
    DOCAGT -->|Fetch encounter\ndata via FHIR| FHIR([FHIR R4 API])
    DOCAGT -->|Generate summary\nGemini 1.5 Pro| VERTEX([Vertex AI])
    MEDAGT -->|Check interactions| RXNAV([RxNav / OpenFDA])
    FUPAGT -->|Readmission risk\nscore inference| MLINF[ML Inference\nService]
    BEDAGT -->|LOS prediction\ninference| MLINF

    FHIR --> DOCAGT
    VERTEX --> DOCAGT
    RXNAV --> MEDAGT
    MLINF --> FUPAGT
    MLINF --> BEDAGT

    DOCAGT -->|Write Document\nDRAFT| DB_W
    MEDAGT -->|Write Medication\nreconciliation| DB_W
    BEDAGT -->|Update Bed status| DB_W
    FUPAGT -->|Write risk score\nSchedule follow-up| DB_W

    DB_W -->|WAL replication| DB_R[(Cloud SQL\nRead Replica)]

    COORD -->|SignalR push\nvia FastAPI hub| SIGNALR[SignalR Hub\nFastAPI]
    SIGNALR -->|Real-time update\nWebSocket| DASHBOARD[Angular PWA\nStaff Dashboard]

    DB_R -->|Dashboard\nGET queries| API[FastAPI\nRead API]
    API --> DASHBOARD

    FUPAGT -->|Publish to\nnotification-requests| NOTIF[Notification\nService]
    NOTIF -->|SMS via Twilio| PATIENT([📱 Patient])
    NOTIF -->|Email via SendGrid| PATIENT

    style PUBSUB fill:#4285F4,color:#fff
    style DB_W fill:#34A853,color:#fff
    style DB_R fill:#34A853,color:#fff
    style STORAGE fill:#FBBC04,color:#000
    style DASHBOARD fill:#EA4335,color:#fff
```

---

## 7. Sequence Diagram — Patient Discharge (UC-003)

> **Actors:** EHR, HL7 Listener, Coordinator Agent, Documentation Agent, Medication Reconciliation Agent, Follow-up Care Agent, Bed Management Agent, Physician, Patient

```mermaid
sequenceDiagram
  autonumber

  participant EHR as 🏥 EHR System
  participant HL7 as HL7 Listener
  participant PS as GCP Pub/Sub
  participant COORD as Coordinator Agent
  participant DOC as Documentation Agent
  participant MED as Med Recon Agent
  participant FUP as Follow-up Agent
  participant BED as Bed Mgmt Agent
  participant ML as ML Inference
  participant FHIR as FHIR R4 API
  participant VTXAI as Vertex AI
  participant DB as Cloud SQL
  participant API as FastAPI / SignalR
  participant UI as Angular Dashboard
  participant PHY as 👨‍⚕️ Physician
  participant PAT as 📱 Patient

  EHR->>HL7: ADT^A03 discharge message (MLLP)
  HL7->>HL7: Archive raw HL7 to Cloud Storage
  HL7-->>EHR: ACK AA (within 200ms)
  HL7->>HL7: Parse PID, PV1, EVN segments
  HL7->>PS: Publish ADTEvent {type:A03, encounterId}

  par Coordinator subscribes
    PS->>COORD: Deliver A03 event
    COORD->>DB: Create AgentTask records (all agents)
    COORD->>DB: Update Encounter.status = DISCHARGING
    COORD->>API: Notify via SignalR → staff dashboard
    API-->>UI: Real-time: "Discharge initiated"
  end

  par Documentation Agent
    PS->>DOC: Deliver A03 event
    DOC->>FHIR: GET Patient, Encounter, Condition, MedicationStatement
    FHIR-->>DOC: Patient data (FHIR R4 resources)
    DOC->>VTXAI: Generate discharge summary (streaming, Gemini 1.5 Pro)
    Note over DOC,VTXAI: 25s timeout; template fallback at 28s
    VTXAI-->>DOC: Structured JSON discharge summary
    DOC->>DOC: Completeness validation
    DOC->>DOC: Translate instructions (patient language)
    DOC->>DB: INSERT Document {type:DISCHARGE_SUMMARY, status:PENDING_REVIEW}
    DOC->>API: Notify: "Discharge summary ready for review"
    API-->>UI: Push: document approval badge
  and Medication Reconciliation Agent
    PS->>MED: Deliver A03 event
    MED->>FHIR: GET MedicationStatement (pre-admit) + MedicationRequest (discharge)
    FHIR-->>MED: Medication lists
    MED->>MED: Compare 3 lists; categorise changes
    MED->>MED: Check drug interactions (RxNav cache → API)
    MED->>DB: INSERT Medication records with conflict/interaction flags
    MED->>DB: INSERT Document {type:MED_SUMMARY}
    MED->>API: Alert if high-risk interaction found
    API-->>UI: Push: pharmacist alert (if triggered)
  and Follow-up Care Agent
    PS->>FUP: Deliver A03 event
    FUP->>ML: POST /predict/readmission {encounterId}
    ML-->>FUP: {risk_score: 0.82, tier: HIGH}
    FUP->>DB: UPDATE Encounter {risk_score:0.82, risk_tier:HIGH}
    FUP->>FUP: Schedule follow-up (within 7 days — BR-003)
    FUP->>DB: INSERT follow-up appointment record
    API-->>UI: Push: HIGH risk flag on patient card
  and Bed Management Agent
    PS->>BED: Deliver A03 event
    BED->>DB: UPDATE Bed {status:DIRTY, current_encounter_id:null}
    BED->>BED: Trigger housekeeping notification (Pub/Sub → Notification Service)
    BED->>API: Refresh mv_bed_board materialised view
    API-->>UI: Push: bed board updated
  end

  PHY->>UI: Open discharge approval queue
  UI->>API: GET /api/v1/encounters/{id}/documents
  API->>DB: SELECT documents WHERE status=PENDING_REVIEW
  DB-->>API: Documents list
  API-->>UI: Discharge summary + medication summary
  PHY->>UI: Review AI-generated discharge summary (dual-pane editor)
  PHY->>UI: Make inline edits (change tracking records authorship)
  PHY->>UI: Click "Approve & Sign"
  UI->>API: PATCH /api/v1/documents/{id}/approve
  API->>DB: UPDATE Document {status:APPROVED, reviewed_by, approved_at}
  API->>DB: INSERT AuditLog {action:APPROVE, entity:DOCUMENT}
  API->>DB: UPDATE Encounter {status:DISCHARGED}
  API-->>UI: Document finalised confirmation

  API->>PS: Publish {type:DISCHARGE_COMPLETE, encounterId}
  PS->>FUP: Deliver DISCHARGE_COMPLETE
  FUP->>FUP: Schedule SMS/email reminders (Notification Service)
  FUP->>PAT: SMS — portal link + appointment confirmation

  PAT->>UI: Opens patient portal link
  UI->>API: GET /portal/instructions (patient JWT)
  API->>DB: SELECT documents WHERE patient_id AND status=APPROVED
  DB-->>API: Discharge instructions (patient language)
  API-->>UI: Personalised discharge instructions
```

---

## 8. Sequence Diagram — Medication Reconciliation (UC-005)

> **Actors:** Medication Reconciliation Agent, FHIR, RxNav, Pharmacist, Physician

```mermaid
sequenceDiagram
  autonumber

  participant PS as GCP Pub/Sub
  participant MED as Med Recon Agent
  participant FHIR as FHIR R4 API
  participant RXNAV as RxNav API
  participant REDIS as Redis Cache
  participant DB as Cloud SQL
  participant API as FastAPI / SignalR
  participant UI as Angular Dashboard
  participant PHARM as 💊 Pharmacist
  participant PHY as 👨‍⚕️ Physician

  PS->>MED: Deliver ADT A01 (Admission) event
  MED->>DB: INSERT AgentTask {agent:MED_RECON, status:IN_PROGRESS}

  MED->>FHIR: GET MedicationStatement?patient={mrn} (pre-admission list)
  FHIR-->>MED: Pre-admission medications (FHIR Bundle)

  MED->>FHIR: GET MedicationAdministration?encounter={id} (inpatient list)
  FHIR-->>MED: Inpatient medications (FHIR Bundle)

  Note over MED: Compare 3 lists — categorise each med as CONTINUED/NEW/STOPPED/DOSE_CHANGED

  loop For each active medication pair combination
    MED->>REDIS: GET drug-interaction:{rxcui1}:{rxcui2}
    alt Cache HIT
      REDIS-->>MED: Interaction result (24h TTL)
    else Cache MISS
      MED->>RXNAV: GET interaction/list?rxcuis={rxcui1,rxcui2}
      RXNAV-->>MED: Interaction severity + description
      MED->>REDIS: SET drug-interaction:{rxcui1}:{rxcui2} TTL 86400
    end
  end

  MED->>MED: Flag: drug-drug interactions by severity
  MED->>MED: Flag: therapeutic duplicates
  MED->>MED: Flag: missing chronic maintenance medications

  MED->>DB: INSERT Medication records {list_type, status, conflict_flag, interaction_severity}

  alt HIGH severity interaction detected
    MED->>API: POST pharmacist alert {severity:HIGH, drug_pair, patient_encounter}
    API->>DB: INSERT AuditLog {action:ALERT, entity:MEDICATION}
    API-->>UI: SignalR push — pharmacist priority alert badge
    PHARM->>UI: Opens medication reconciliation queue
    UI->>API: GET /api/v1/encounters/{id}/medications
    API->>DB: SELECT medications WHERE encounter_id ORDER BY interaction_severity DESC
    DB-->>API: Medication lists with flags
    API-->>UI: Three-panel view (pre-admit | inpatient | discharge) + interaction warnings
    PHARM->>PHY: Contacts prescribing physician (tracked in system)
    PHARM->>UI: Documents resolution (medication changed / accepted with plan)
    UI->>API: PATCH /api/v1/medications/{id}/resolve {resolution, note}
    API->>DB: UPDATE Medication + INSERT AuditLog
    API-->>UI: Alert cleared
  else No HIGH severity interactions
    MED->>API: POST task completion
    API-->>UI: SignalR push — reconciliation complete (green status)
  end

  MED->>MED: Generate patient-readable medication change summary
  MED->>DB: INSERT Document {type:MED_SUMMARY, status:PENDING_REVIEW}
  MED->>DB: UPDATE AgentTask {status:COMPLETE, result:{med_count, alerts}}

  Note over MED,DB: 24-hour SLA from A01 event — escalates to charge pharmacist if breached (BR-002)
```

---

## 9. Sequence Diagram — Patient Chatbot (UC-008)

> **Actors:** Patient, Angular PWA (Patient Portal), Patient Communication Agent, Vertex AI, Care Team

```mermaid
sequenceDiagram
  autonumber

  participant PAT as 📱 Patient
  participant PWA as Angular PWA\n(Patient Portal)
  participant API as FastAPI Backend
  participant DB as Cloud SQL
  participant REDIS as Redis Cache
  participant COMMS as Patient Comms Agent
  participant VTXAI as Vertex AI\n(Gemini Flash)
  participant NURSE as 👩‍⚕️ On-call Nurse
  participant NOTIFY as Notification Service

  PAT->>PWA: Opens portal link (from SMS)
  PWA->>API: POST /api/v1/auth/patient/otp {encounter_token}
  API->>API: Validate encounter portal token (signed, 24h expiry)
  API->>NOTIFY: Trigger OTP via Twilio Verify
  NOTIFY-->>PAT: SMS — 6-digit OTP
  PAT->>PWA: Enters OTP
  PWA->>API: POST /api/v1/auth/patient/verify {otp}
  API->>API: Validate OTP (hash compare, 10-min expiry)
  API-->>PWA: Patient JWT (encounter-scoped, 60-min expiry)

  PWA->>API: GET /portal/instructions (Bearer patient JWT)
  API->>DB: SELECT documents WHERE encounter_id AND status=APPROVED
  DB-->>API: Discharge instructions (patient language)
  API-->>PWA: Personalised discharge instructions
  PWA-->>PAT: Displays instructions + chatbot widget

  PAT->>PWA: Types question: "Can I take ibuprofen with my new medication?"
  PWA->>API: POST /api/v1/chat {message, encounter_id}
  API->>REDIS: GET conversation-history:{encounter_id}
  REDIS-->>API: Previous messages (last 10, 2K tokens max)

  API->>DB: SELECT documents WHERE encounter_id AND type=DISCHARGE_SUMMARY AND status=APPROVED
  DB-->>API: Discharge summary context (4K tokens max)

  API->>COMMS: Forward to agent {message, context, history}
  COMMS->>COMMS: Check urgency signals (chest pain, bleeding, can't breathe, etc.)
  
  alt Urgency signal detected
    COMMS-->>API: {urgent:true, emergency_message}
    API-->>PWA: Emergency response + 911 / hospital number
    API->>NOTIFY: Publish high-priority care team alert
    NOTIFY->>NURSE: SMS + dashboard push alert
    Note over NURSE: Care team responds within 2 minutes (FR-062)
  else Standard question
    COMMS->>VTXAI: POST chat completion\n{system_prompt, patient_context, history, question}
    Note over COMMS,VTXAI: Context window: system(2K) + summary(4K) + history(2K) = 8K max
    VTXAI-->>COMMS: Chatbot response (streamed, Gemini Flash, <3s)
    COMMS->>COMMS: Scope check — answer references only patient's own discharge data
    COMMS-->>API: {response, escalation_recommended:false}
    API->>REDIS: APPEND conversation-history:{encounter_id} [question, response]
    API->>DB: INSERT ChatbotTranscript {direction, message_encrypted, sent_at}
    API-->>PWA: Streamed response
    PWA-->>PAT: Chatbot answer + "Connect with Care Team" option
  end

  opt Patient requests human escalation
    PAT->>PWA: Clicks "Connect with Care Team"
    PWA->>API: POST /api/v1/chat/escalate {encounter_id}
    API->>NOTIFY: Publish escalation request → care team
    NOTIFY->>NURSE: Dashboard alert + SMS
    API-->>PWA: "Care team notified — expected response within 2 minutes"
    NURSE->>UI: Acknowledges escalation in dashboard
    UI->>API: PATCH /api/v1/chat/escalation/{id}/acknowledge
    API-->>PWA: "Your nurse [Name] has been notified"
  end
```

---

## 10. Sequence Diagram — Staff Authentication (UC-010)

> **Actors:** Staff Browser, Angular PWA, FastAPI, Identity Provider (SSO)

```mermaid
sequenceDiagram
  autonumber

  participant BROWSER as 🖥️ Staff Browser
  participant PWA as Angular PWA
  participant API as FastAPI Backend
  participant IDP as Identity Provider\n(SSO / OIDC)
  participant REDIS as Redis\n(Token Blocklist)
  participant DB as Cloud SQL

  BROWSER->>PWA: Navigate to /dashboard
  PWA->>PWA: AuthGuard: no valid JWT in memory
  PWA->>IDP: Redirect to SSO login (OIDC Authorization Code Flow)
  BROWSER->>IDP: User enters credentials + MFA
  IDP->>IDP: Validate credentials + verify MFA (amr includes mfa)
  IDP-->>BROWSER: Redirect to /callback?code={auth_code}
  BROWSER->>PWA: Load /callback with auth_code
  PWA->>IDP: POST /token (exchange auth_code for id_token + access_token)
  IDP-->>PWA: id_token (JWT with sub, email, roles, amr claims)

  PWA->>API: POST /api/v1/auth/token {id_token}
  API->>API: Fetch OIDC JWKS (1h memory cache)
  API->>API: Validate id_token signature + expiry
  API->>API: Verify amr claim includes mfa
  API->>API: Extract role claims → map to RBAC permissions

  API->>DB: UPSERT AppUser {idp_subject, email, role, last_login}
  API->>DB: INSERT AuditLog {action:LOGIN, user_id, ip_address}
  API-->>PWA: App JWT (15-min expiry, in-memory only — NOT localStorage)

  PWA->>PWA: Load role-specific dashboard layout
  PWA->>API: GET /api/v1/dashboard (Bearer app_jwt)
  API->>API: Validate JWT signature + expiry
  API->>REDIS: GET blocklist:{jti} (check if token revoked)
  REDIS-->>API: null (not revoked)
  API->>API: RBAC: role=NURSE → filter to unit-scoped patient data
  API->>DB: SELECT via read replica — mv_risk_dashboard WHERE unit={user_unit}
  DB-->>API: Risk-stratified patient list
  API-->>PWA: Role-filtered dashboard data
  PWA-->>BROWSER: Renders dashboard with real-time SignalR connection

  Note over PWA,API: JWT refresh via silent renew every 12 minutes\nIdle timeout: 30 minutes → redirect to SSO (BR-013)

  opt Session timeout
    PWA->>PWA: 30min idle timer fires
    PWA->>API: POST /api/v1/auth/logout
    API->>REDIS: SET blocklist:{jti} = true TTL={remaining_expiry}
    API->>DB: INSERT AuditLog {action:LOGOUT}
    API-->>PWA: 200 OK
    PWA->>PWA: Clear in-memory JWT
    PWA->>IDP: Redirect to SSO logout endpoint
  end
```

---

## 11. Deployment Diagram — GCP Infrastructure

> **Deployment view** · GCP resources, networking, and service boundaries

```mermaid
flowchart TB
  subgraph INTERNET ["🌐 Internet"]
    BROWSER["🖥️ Staff Browser\n(Angular PWA)"]
    MOBILE["📱 Patient Mobile\n(PWA)"]
    EHR_SYS["🏥 EHR System\n(HL7 MLLP)"]
  end

  subgraph GCP_GLOBAL ["☁️ GCP Global (CDN + WAF)"]
    CDN["Cloud CDN\n+ Cloud Storage\n(Angular PWA assets)"]
    ARMOR["Cloud Armor\n(WAF + DDoS)\nOWASP Top 10 rules\nRate: 1000 req/min/user"]
    LB["Cloud Load Balancer\n(HTTPS / TLS 1.3\ntermination)"]
  end

  subgraph GCP_REGION ["☁️ GCP Region: us-central1 (multi-AZ)"]

    subgraph VPC ["🔒 VPC: smarthandoff-vpc (10.0.0.0/16)"]

      subgraph SUBNET_SVC ["Subnet: services (10.0.1.0/24)"]
        API_SVC["FastAPI Backend\nCloud Run\nmin=2 max=20\n2vCPU / 2GB"]
        HL7_SVC["HL7 Listener\nCloud Run\nmin=1 max=10\n1vCPU / 512MB\nTCP :2575"]
        COORD_SVC["Coordinator Agent\nCloud Run\nmin=1 max=10"]
        DOC_SVC["Documentation Agent\nCloud Run\nmin=1 max=10\n2vCPU / 4GB"]
        MED_SVC["Med Recon Agent\nCloud Run\nmin=1 max=10"]
        BED_SVC["Bed Mgmt Agent\nCloud Run\nmin=1 max=5"]
        FUP_SVC["Follow-up Agent\nCloud Run\nmin=1 max=10"]
        COMMS_SVC["Comms Agent\nCloud Run\nmin=1 max=10"]
        ML_SVC["ML Inference\nCloud Run\nmin=1 max=5\n2vCPU / 2GB"]
        NOTIF_SVC["Notification Svc\nCloud Run\nmin=1 max=5"]
      end

      subgraph SUBNET_DATA ["Subnet: data (10.0.2.0/24)"]
        PGSQL_PRI["Cloud SQL Primary\nPostgreSQL 15\n10.0.2.10\nCMEK + HA\n4vCPU / 16GB"]
        PGSQL_REP["Cloud SQL Replica\nPostgreSQL 15\nRead replica\nMaterialised views"]
        REDIS_CACHE["Cloud Memorystore\nRedis 7\n10.0.2.20\n2GB Standard tier"]
      end

      VPC_CONN["VPC Connector\n10.8.0.0/28\n(Cloud Run → data subnet)"]
    end

    subgraph GCP_MANAGED ["GCP Managed Services"]
      PUBSUB["Cloud Pub/Sub\nadt-events topic\nPer-agent subscriptions\n+ DLQ per subscription"]
      VERTEX_AI["Vertex AI\n(Gemini 1.5 Pro)\n(Gemini Flash — chatbot)"]
      SECRET_MGR["Secret Manager\nEncryption keys\nAPI credentials\nDB passwords"]
      CLOUD_STORAGE["Cloud Storage\nHIPAA CMEK buckets:\nhl7-archive/\nml-models/\naudit-export/ (WORM)"]
      CLOUD_LOG["Cloud Logging\n+ Cloud Monitoring\n(structured logs, metrics\nno PHI in logs)"]
      CLOUD_TRACE["Cloud Trace\n(OpenTelemetry)"]
      BIGQUERY["BigQuery\n(de-identified analytics\nnightly export)"]
    end
  end

  subgraph EXTERNAL ["🔗 External Services"]
    IDP_EXT["Identity Provider\nSSO / OIDC + MFA"]
    TWILIO_EXT["Twilio\nSMS + Verify OTP"]
    SENDGRID_EXT["SendGrid\nEmail delivery"]
    RXNAV_EXT["RxNav / OpenFDA\nDrug interactions"]
    FHIR_EXT["FHIR R4 API\nEHR Patient data"]
  end

  BROWSER & MOBILE --> CDN
  BROWSER & MOBILE --> ARMOR --> LB --> API_SVC
  EHR_SYS -->|MLLP TCP| HL7_SVC

  API_SVC --- VPC_CONN
  COORD_SVC & DOC_SVC & MED_SVC & BED_SVC & FUP_SVC & COMMS_SVC & ML_SVC & NOTIF_SVC --- VPC_CONN
  HL7_SVC --- VPC_CONN

  VPC_CONN --> PGSQL_PRI & PGSQL_REP & REDIS_CACHE

  HL7_SVC --> PUBSUB
  PUBSUB --> COORD_SVC & DOC_SVC & MED_SVC & BED_SVC & FUP_SVC & COMMS_SVC

  DOC_SVC & COMMS_SVC --> VERTEX_AI
  FUP_SVC & BED_SVC --> ML_SVC
  MED_SVC --> RXNAV_EXT
  NOTIF_SVC --> TWILIO_EXT & SENDGRID_EXT
  API_SVC --> IDP_EXT
  DOC_SVC & MED_SVC & FUP_SVC --> FHIR_EXT

  API_SVC & HL7_SVC & COORD_SVC --> SECRET_MGR
  HL7_SVC --> CLOUD_STORAGE
  API_SVC --> CLOUD_LOG & CLOUD_TRACE
  PGSQL_PRI --> BIGQUERY

  style GCP_REGION fill:#E8F0FE,stroke:#4285F4
  style VPC fill:#FFF3E0,stroke:#F57C00
  style GCP_MANAGED fill:#E8F5E9,stroke:#34A853
  style EXTERNAL fill:#FCE4EC,stroke:#E91E63
  style INTERNET fill:#F3E5F5,stroke:#9C27B0
```

---

## 12. Class Diagram — Domain Model

> **Domain model** · Core domain classes, relationships, and key methods

```mermaid
classDiagram
  direction TB

  class Patient {
    +UUID patient_id
    +String mrn
    +String first_name
    +String last_name
    +Date dob
    +String gender
    +String language
    +String phone
    +String email
    +DateTime created_at
    +DateTime deleted_at
    +get_active_encounter() Encounter
    +get_preferred_language() String
  }

  class Encounter {
    +UUID encounter_id
    +UUID patient_id
    +DateTime admit_date
    +DateTime discharge_date
    +String unit
    +String attending_md
    +EncounterStatus status
    +Decimal risk_score
    +RiskTier risk_tier
    +transition(new_status, adt_event) void
    +is_high_risk() bool
    +get_pending_documents() List~Document~
  }

  class ADTEvent {
    +UUID event_id
    +UUID encounter_id
    +ADTEventType event_type
    +DateTime event_time
    +String source_system
    +String source_message_id
    +ProcessingStatus processing_status
    +is_cancellation() bool
    +get_triggerable_agents() List~AgentType~
  }

  class Medication {
    +UUID medication_id
    +UUID encounter_id
    +String drug_name
    +String rxcui
    +String dosage
    +String frequency
    +MedListType list_type
    +MedStatus status
    +Boolean conflict_flag
    +InteractionSeverity interaction_severity
    +Boolean duplicate_flag
    +is_high_risk_class() bool
  }

  class AgentTask {
    +UUID task_id
    +UUID encounter_id
    +AgentType agent_type
    +TaskStatus status
    +DateTime start_time
    +DateTime end_time
    +Integer duration_ms
    +JSON result
    +Integer retry_count
    +is_overdue(sla_seconds) bool
    +mark_complete(result) void
    +mark_failed(error) void
  }

  class Document {
    +UUID document_id
    +UUID encounter_id
    +DocumentType document_type
    +String content
    +String language
    +GenerationType generation_type
    +DocumentStatus status
    +Boolean ai_assisted_label
    +DateTime approved_at
    +UUID reviewed_by_user_id
    +approve(clinician_id) void
    +reject(reason) void
    +is_ready_for_patient() bool
  }

  class Bed {
    +UUID bed_id
    +String unit
    +String room
    +String bed_label
    +BedType bed_type
    +BedStatus status
    +UUID current_encounter_id
    +DateTime predicted_discharge_at
    +assign(encounter_id) void
    +mark_dirty() void
    +mark_clean() void
    +is_available() bool
  }

  class AppUser {
    +UUID user_id
    +String email
    +UserRole role
    +String idp_subject
    +Boolean active
    +DateTime last_login
    +has_permission(resource, action) bool
    +deprovision() void
  }

  class AuditLog {
    +UUID audit_id
    +UUID user_id
    +String user_role
    +AuditAction action
    +String entity_type
    +UUID entity_id
    +String ip_address
    +DateTime action_at
    +JSON metadata
  }

  class ChatbotTranscript {
    +UUID transcript_id
    +UUID encounter_id
    +String direction
    +String message
    +Boolean urgency_flag
    +Boolean escalated
    +UUID escalated_to_user_id
    +DateTime sent_at
    +detect_urgency() bool
  }

  %% Enumerations
  class EncounterStatus {
    <<enumeration>>
    REGISTERED
    ADMITTED
    TRANSFERRED
    DISCHARGED
    CANCELLED
    ARCHIVED
  }

  class ADTEventType {
    <<enumeration>>
    A01_ADMIT
    A02_TRANSFER
    A03_DISCHARGE
    A04_REGISTER
    A08_UPDATE
    A11_CANCEL_ADMIT
    A12_CANCEL_TRANSFER
    A13_CANCEL_DISCHARGE
  }

  class AgentType {
    <<enumeration>>
    COORDINATOR
    DOCUMENTATION
    MED_RECON
    BED_MGMT
    FOLLOWUP
    COMMS
  }

  class DocumentType {
    <<enumeration>>
    DISCHARGE_SUMMARY
    PATIENT_INSTRUCTIONS
    TRANSFER_NOTE
    MED_SUMMARY
  }

  class UserRole {
    <<enumeration>>
    ADMIN
    PHYSICIAN
    NURSE
    PHARMACIST
    BED_MANAGER
    READ_ONLY
  }

  %% Relationships
  Patient "1" --> "0..*" Encounter : has
  Encounter "1" --> "0..*" ADTEvent : triggers
  Encounter "1" --> "0..*" Medication : has
  Encounter "1" --> "0..*" AgentTask : generates
  Encounter "1" --> "0..*" Document : produces
  Encounter "1" --> "0..1" Bed : occupies
  Encounter "1" --> "0..*" ChatbotTranscript : has
  AgentTask "1" --> "0..*" Document : generates
  AppUser "1" --> "0..*" AuditLog : creates
  AppUser "1" --> "0..*" Document : reviews
  AppUser "1" --> "0..*" ChatbotTranscript : escalated_to

  Encounter ..> EncounterStatus : uses
  ADTEvent ..> ADTEventType : uses
  AgentTask ..> AgentType : uses
  Document ..> DocumentType : uses
  AppUser ..> UserRole : uses
```

---

*End of SmartHandoff Visual Design Model — Version 1.0 | Generated: 2026-07-13*
