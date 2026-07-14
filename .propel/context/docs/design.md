# SmartHandoff — Architecture Design Specification

> **Artifact:** design | **Version:** 1.0 | **Status:** Draft  
> **Date:** 2026-07-13 | **Upstream:** SRS v1.0 | **Workflow:** /design-architecture  
> **Architect:** SmartHandoff Project Team

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Architecture Decision Records (ADRs)](#2-architecture-decision-records-adrs)
3. [System Component Design](#3-system-component-design)
4. [Technology Stack](#4-technology-stack)
5. [Technical Requirements (TR)](#5-technical-requirements-tr)
6. [Data Architecture Requirements (DR)](#6-data-architecture-requirements-dr)
7. [Architectural Integration Requirements (AIR)](#7-architectural-integration-requirements-air)
8. [Security Architecture](#8-security-architecture)
9. [Deployment Architecture](#9-deployment-architecture)
10. [Cross-Cutting Concerns](#10-cross-cutting-concerns)
11. [Non-Functional Requirement Validation](#11-non-functional-requirement-validation)
12. [Architecture Risk Register](#12-architecture-risk-register)
13. [Glossary](#13-glossary)

---

## 1. Architecture Overview

### 1.1 Architectural Style

SmartHandoff adopts an **Event-Driven Multi-Agent Microservices** architecture. This style is mandated by three intersecting constraints:

1. **Real-time healthcare events** — HL7 ADT messages arrive asynchronously and must trigger coordinated multi-step workflows within 5-second SLAs (FR-001, NFR-003)
2. **AI agent parallelism** — Six specialised agents must execute concurrently without coupling (FR-010, FR-011)
3. **HIPAA compliance boundary** — PHI must stay within defined service perimeters with immutable audit trails (BR-020, SEC-006)

### 1.2 Architectural Principles

| Principle | Application |
|-----------|-------------|
| **Event-first** | All ADT events published to Pub/Sub before any processing begins — no direct coupling between intake and agents |
| **Agents as consumers** | Each AI agent is an independent Pub/Sub subscriber with its own retry/dead-letter queue |
| **Read-model separation** | Dashboard queries use read-optimised views; writes go through the command API (CQRS) |
| **Zero-trust perimeter** | Every service-to-service call carries a signed JWT; no implicit trust between Cloud Run services |
| **PHI containment** | PHI never crosses service boundaries in plaintext logs; field-level encryption enforced at ORM layer |
| **Human-in-the-loop** | AI agents produce drafts only; human approval gates enforced at API level before status transitions |

### 1.3 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          SMARTHANDOFF — SYSTEM ARCHITECTURE                      │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   EXTERNAL SYSTEMS          │    SMARTHANDOFF PLATFORM         │  GOOGLE CLOUD   │
│   ────────────────          │    ───────────────────────────   │  ─────────────  │
│                             │                                  │                 │
│  ┌─────────────────┐        │  ┌────────────────────────────┐  │  ┌───────────┐  │
│  │   EHR System    │        │  │   Angular 17 PWA           │  │  │ Cloud Run │  │
│  │  HL7 ADT/FHIR   │        │  │   (Staff Dashboard +       │  │  │ (Agents)  │  │
│  └────────┬────────┘        │  │    Patient Portal)         │  │  └─────┬─────┘  │
│           │MLLP/TCP         │  └───────────┬────────────────┘  │        │        │
│           │                 │              │REST/WS            │        │        │
│  ┌────────▼────────┐        │  ┌───────────▼────────────────┐  │  ┌─────▼─────┐  │
│  │  HL7 Listener   │◄──────►│  │   FastAPI Backend          │  │  │ Vertex AI │  │
│  │  (MLLP→HTTP)    │        │  │   (REST + SignalR)         │◄─►│  │ (Gemini)  │  │
│  └────────┬────────┘        │  └───────────┬────────────────┘  │  └───────────┘  │
│           │                 │              │                    │                 │
│           │                 │  ┌───────────▼────────────────┐  │  ┌───────────┐  │
│  ┌────────▼────────┐        │  │     GCP Pub/Sub            │  │  │ Cloud SQL │  │
│  │   FHIR R4 API   │        │  │   (adt-events topic)       │  │  │(PostgreSQL│  │
│  │   (Read-only)   │        │  └─────┬───────┬──────────────┘  │  └─────┬─────┘  │
│  └─────────────────┘        │        │       │                  │        │        │
│                             │   ┌────▼──┐ ┌──▼────┐            │        │        │
│  ┌─────────────────┐        │   │Agent  │ │Agent  │            │  ┌─────▼─────┐  │
│  │   Identity      │        │   │Subs.1 │ │Subs.2 │  ...       │  │ Cloud     │  │
│  │   Provider SSO  │◄──────►│   └───────┘ └───────┘            │  │ Storage   │  │
│  └─────────────────┘        │                                   │  │ (Audit)   │  │
│                             │                                   │  └───────────┘  │
│  ┌─────────────────┐        │                                   │  ┌───────────┐  │
│  │  Twilio/SendGrid│◄───────┤                                   │  │ Secret    │  │
│  │  (SMS/Email)    │        │                                   │  │ Manager   │  │
│  └─────────────────┘        │                                   │  └───────────┘  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architecture Decision Records (ADRs)

### ADR-001: Event-Driven Architecture via GCP Pub/Sub

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | ADT events arrive in bursts; agents must process independently without blocking intake |
| **Decision** | All ADT events published to GCP Pub/Sub `adt-events` topic; each agent type subscribes on a dedicated subscription with its own dead-letter queue |
| **Consequences** | (+) Agent failures don't block event intake; (+) horizontal agent scaling independent of API; (−) eventual consistency between EHR and dashboard state |
| **NFR Traceability** | NFR-003 (<5s processing), NFR-010 (scale to 5,000 events/day) |

### ADR-002: GCP Cloud Run for Stateless Service Hosting

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Constraint C-05 mandates GCP; variable ADT volume requires cost-efficient auto-scaling |
| **Decision** | All backend services deployed as Cloud Run services; min-instances=1 for latency-sensitive paths (API, SignalR hub) |
| **Consequences** | (+) Auto-scaling 0→N within 10 seconds; (+) per-request billing; (−) cold-start latency risk — mitigated by min-instances=1 |
| **NFR Traceability** | NFR-005 (500 concurrent), NFR-010 (10× scale), NFR-020 (99.9% uptime) |

### ADR-003: PostgreSQL (Cloud SQL) as System of Record

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | HIPAA requires ACID transactional writes, encryption, and immutable audit logs |
| **Decision** | Cloud SQL PostgreSQL 15 with CMEK; separate `audit_log` table with append-only row security; read replicas for dashboard queries |
| **Consequences** | (+) HIPAA compliance via CMEK + WAL; (+) mature ACID guarantees; (−) horizontal write scaling requires sharding in Phase 3 |
| **NFR Traceability** | NFR-042 (zero data loss), NFR-043 (4-hour backup), SEC-004 |

### ADR-004: LangChain + Vertex AI (Gemini) for Agent Orchestration

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Six agents require LLM calls, tool use, structured output; Vertex AI mandated for GCP alignment (Constraint C-05) |
| **Decision** | LangChain as agent framework; Vertex AI Gemini 1.5 Pro as primary LLM; Scikit-learn models served as Cloud Run microservice; template fallback if Vertex AI unavailable |
| **Consequences** | (+) LangChain abstracts LLM provider — enables open-source fallback (A-06); (+) structured output via Pydantic schemas; (−) Vertex AI token costs must be monitored |
| **NFR Traceability** | NFR-004 (<30s doc generation), FR-020, FR-052 |

### ADR-005: Angular 17 PWA with SignalR

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Staff require real-time ADT feeds; patients require mobile-first portal without app installation |
| **Decision** | Single Angular 17 PWA with lazy-loaded feature modules; SignalR WebSocket hub for real-time push; service worker for offline patient instruction caching |
| **Consequences** | (+) One codebase for staff dashboard and patient portal; (+) PWA installability; (−) Angular bundle size requires aggressive lazy loading |
| **NFR Traceability** | NFR-001 (<2s load), NFR-006 (<1s SignalR latency), NFR-033 (mobile) |

### ADR-006: CQRS Pattern for Dashboard Performance

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Dashboard queries are read-heavy and aggregated; write path requires ACID guarantees |
| **Decision** | Commands (ADT processing, document approval) → PostgreSQL primary; queries → PostgreSQL read replica with materialised views |
| **Consequences** | (+) Read replica offloads dashboard queries; (+) materialised views pre-compute KPIs; (−) replication lag (<1s) acceptable for non-critical reads |
| **NFR Traceability** | NFR-002 (<500ms API p95), NFR-005 (500 concurrent) |

### ADR-007: Field-Level PHI Encryption at ORM Layer

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | HIPAA requires PHI encrypted at rest; Cloud SQL CMEK encrypts blocks but application-layer encryption prevents DB admin access to PHI |
| **Decision** | SQLAlchemy custom TypeDecorators encrypt PHI fields (FirstName, LastName, DOB, Phone, Email, MRN, document Content) using AES-256-GCM; keys from GCP Secret Manager |
| **Consequences** | (+) Defense-in-depth: two encryption layers; (+) PHI never in plaintext in DB or logs; (−) encrypted fields not directly queryable (MRN uses deterministic encryption for lookups) |
| **NFR Traceability** | SEC-004, BR-020, BR-021 |

---

## 3. System Component Design

### 3.1 Component Inventory

| Component | Type | Technology | Responsibility |
|-----------|------|------------|----------------|
| HL7 Listener | Cloud Run | Python + hl7apy | MLLP TCP ingestion → HTTP bridge → Pub/Sub publish |
| API Gateway | Cloud Run | Python FastAPI | REST API, JWT auth, RBAC enforcement, SignalR hub |
| Transition Coordinator Agent | Cloud Run | Python LangChain | Workflow orchestration, task dispatch, SLA tracking |
| Documentation Agent | Cloud Run | Python LangChain + Vertex AI | Discharge summary, patient instructions, completeness checks |
| Medication Reconciliation Agent | Cloud Run | Python LangChain + RxNav | Med list comparison, interaction detection, pharmacist alerts |
| Bed Management Agent | Cloud Run | Python + Scikit-learn | Bed board, discharge prediction, ED boarding alerts |
| Follow-up Care Agent | Cloud Run | Python LangChain + Scikit-learn | Risk scoring, appointment scheduling, reminder dispatch |
| Patient Communication Agent | Cloud Run | Python LangChain + Vertex AI | Chatbot, urgency detection, escalation routing |
| ML Inference Service | Cloud Run | Python FastAPI + Scikit-learn | Serve readmission risk and discharge time models |
| Notification Service | Cloud Run | Python | Twilio SMS + SendGrid email with retry |
| Angular PWA | Cloud Storage + CDN | Angular 17 | Staff dashboard, patient portal, real-time updates |
| Cloud SQL (Primary) | Managed DB | PostgreSQL 15 | Transactional writes, CMEK encrypted, WAL enabled |
| Cloud SQL (Replica) | Managed DB | PostgreSQL 15 | Read queries, materialised view host |
| GCP Pub/Sub | Managed Messaging | GCP | ADT event bus with per-agent subscriptions + DLQ |
| Cloud Memorystore | Managed Cache | Redis 7 | Token blocklist, drug interaction cache, bed board cache |
| GCP Secret Manager | Managed Secrets | GCP | API keys, encryption keys, service credentials |
| Cloud Armor | WAF/DDoS | GCP | OWASP rule set, rate limiting, geo-blocking |

### 3.2 Agent Container Pattern

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AGENT SUBSYSTEM ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  GCP Pub/Sub: Topic adt-events                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Subscription per agent type (with Dead Letter Queue):      │    │
│  │  coordinator-sub │ docs-agent-sub │ medrecon-sub │ ...      │    │
│  └───────────────────────────┬─────────────────────────────────┘    │
│                              │                                       │
│  Each Agent Container (Cloud Run):                                   │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Pub/Sub Consumer → LangChain Executor → Tool Set           │    │
│  │      (async pull)     (+ Prompt Template)   (FHIR, LLM,    │    │
│  │                                              DB, API)       │    │
│  │                                   │                         │    │
│  │                                   ▼                         │    │
│  │                       Pydantic Output Schema                │    │
│  │                       (structured output validation)        │    │
│  │                                   │                         │    │
│  │                    ┌──────────────┴──────────────┐          │    │
│  │                    ▼                             ▼          │    │
│  │            AgentTask DB Write          SignalR Push (UI)    │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 API Layer Design

```
FastAPI Backend — Middleware Stack (request order):
  1. Cloud Armor WAF (external — before Cloud Run)
  2. TLS 1.3 Termination (Cloud Run ingress)
  3. Rate Limiter (slowapi — 1,000 req/min per user)
  4. JWT Validator (python-jose + OIDC JWKS)
  5. RBAC Enforcer (role claims → permission policy)
  6. PHI Log Sanitiser (strips PHI before Cloud Logging)
  7. HIPAA Audit Logger (structured, append-only)
  8. Request Handler (router dispatch)

Routers (versioned /api/v1/):
  /auth        /encounters  /patients
  /documents   /tasks       /medications
  /beds        /analytics   /admin/users
  /admin/audit

SignalR Hub: /hubs/dashboard
  Groups: encounter-{id}, unit-{unitId}, role-{roleName}
```

### 3.4 Frontend Module Architecture

```
smarthandoff-angular/
├── core/                    # Singleton services, guards, interceptors
│   ├── auth/                # OAuthService, JwtInterceptor, AuthGuard
│   ├── signalr/             # SignalRService (real-time hub connection)
│   ├── api/                 # Generated client (openapi-generator)
│   └── audit/               # Client-side audit event emitter
│
├── shared/                  # Reusable components, pipes, directives
│   ├── components/          # RiskBadge, AILabel, SkeletonLoader, Toast
│   └── pipes/               # MaskMrn, ReadingLevel, RelativeTime
│
└── features/                # Lazy-loaded feature modules (per role)
    ├── dashboard/           # FR-070–074: ADT feed, metrics, agent status
    ├── patients/            # FR-071: Patient list + detail
    ├── medications/         # FR-030–035: Med reconciliation UI
    ├── documents/           # FR-020–024: Dual-pane review editor
    ├── beds/                # FR-040–043: Bed board
    ├── analytics/           # FR-073: KPI dashboards (Chart.js)
    ├── patient-portal/      # FR-060–065: Instructions + chatbot
    └── admin/               # FR-074: User management, audit log
```

---

## 4. Technology Stack

### 4.1 Technology Selection Matrix

| Layer | Technology | Version | Justification | Drivers |
|-------|-----------|---------|---------------|---------|
| Frontend Framework | Angular | 17 | BRD-mandated; PWA support; strict TypeScript | NFR-001, NFR-033 |
| UI Components | Angular Material | 17 | WCAG 2.1 AA built-in | NFR-034 |
| Real-time (Client) | @microsoft/signalr | 7.x | WebSocket with HTTP fallback; group broadcast | NFR-006, FR-012 |
| Charts | Chart.js | 4.x | Lightweight KPI dashboards | FR-073 |
| PWA | Angular Service Worker | 17 | Offline instruction caching | A-04 |
| Backend Framework | Python FastAPI | 0.110+ | Async-native; OpenAPI auto-generation; Pydantic v2 | NFR-002 |
| ASGI Server | Uvicorn + Gunicorn | latest | Production multi-worker; Cloud Run compatible | NFR-005 |
| ORM | SQLAlchemy | 2.x | Async support; PHI field-level encryption decorators | BR-020, ADR-007 |
| DB Migration | Alembic | latest | Version-controlled DDL migrations | DR-001 |
| Agent Framework | LangChain | 0.2+ | Tool abstraction; Vertex AI integration; structured output | ADR-004 |
| Primary LLM | Vertex AI Gemini 1.5 Pro | latest | GCP-native; 1M token context; JSON output mode | FR-020, FR-060 |
| LLM Fallback | LLaMA 3 (Cloud Run GPU) | 3.1 8B | Open-source fallback per Assumption A-06 | A-06 |
| ML Framework | Scikit-learn | 1.5+ | Readmission risk (LogisticRegression); LOS prediction (GradientBoosting) | FR-052, FR-040 |
| ML Serving | FastAPI (dedicated service) | 0.110+ | Lightweight REST inference endpoint | FR-052 |
| Drug Interaction | RxNav / OpenFDA API | REST | NIH-maintained; free; major interaction coverage | FR-031 |
| HL7 Parsing | hl7apy | 1.3.4 | Python HL7 v2.x parser; ADT segment support | FR-003 |
| FHIR Client | fhir.resources + httpx | latest | Typed FHIR R4 models; async HTTP client | FR-030 |
| Authentication | python-jose + Authlib | latest | JWT validation; OIDC token exchange | SEC-001 |
| Message Bus | GCP Pub/Sub | managed | Durable, ordered; per-agent subscriptions with DLQ | ADR-001 |
| Database | Cloud SQL PostgreSQL | 15 | ACID; CMEK; read replicas; WAL for RPO | ADR-003 |
| Cache | Cloud Memorystore Redis | 7 | Token blocklist; drug interaction cache; bed board | ADR-006 |
| Compute | Cloud Run | managed | Auto-scaling; per-request billing; VPC connector | ADR-002 |
| CDN / Static | Cloud CDN + Cloud Storage | managed | Angular PWA hosting; global edge caching | NFR-001 |
| Secrets | GCP Secret Manager | managed | API keys, encryption keys, DB credentials | SEC-004 |
| WAF | Cloud Armor | managed | OWASP Top 10; rate limiting; DDoS protection | SEC-012 |
| Observability | Cloud Monitoring + Logging | managed | Structured logs; custom metrics; SLO tracking | NFR-020 |
| Tracing | Cloud Trace (OpenTelemetry) | managed | Distributed traces across agent chain | TR-010 |
| SMS | Twilio Programmable SMS | REST API | Medication reminders; OTP authentication | FR-051, SEC-003 |
| Email | SendGrid | REST API | Email notifications and patient portal links | FR-051 |
| IaC | Terraform | 1.7+ | GCP infrastructure as code | TR-018 |
| CI/CD | Cloud Build + Cloud Deploy | managed | Build, test, canary deploy pipeline | TR-020 |

---

## 5. Technical Requirements (TR)

### 5.1 Performance Technical Requirements

| ID | Requirement | Target | Implementation Constraint | NFR Ref |
|----|-------------|--------|--------------------------|---------|
| TR-001 | API response time (p95) | <500ms | FastAPI async handlers; read replica for GET; connection pool ≥20; SQLAlchemy `selectinload` to avoid N+1 | NFR-002 |
| TR-002 | Angular initial load | <2 seconds | Bundle size <500KB (main chunk); lazy-load all features; serve from Cloud CDN edge | NFR-001 |
| TR-003 | SignalR push latency | <1 second | SignalR hub min-instances=2; group-scoped broadcasts; MessagePack binary protocol | NFR-006 |
| TR-004 | AI document generation | <30 seconds | Vertex AI streaming; LangChain `streaming=True`; timeout=25s with template fallback at 28s | NFR-004 |
| TR-005 | ADT ingestion throughput | ≥5,000/day | Pub/Sub 100 ordering keys; HL7 Listener max-instances=10; async ACK post Pub/Sub confirm | NFR-010 |
| TR-006 | Chatbot response time | <3 seconds | Gemini Flash model for chatbot; context window capped at 8K tokens | FR-062 |
| TR-007 | ML inference latency | <500ms | Scikit-learn models pre-loaded in container memory; no cold-load per request | FR-052, FR-040 |

### 5.2 Scalability Technical Requirements

| ID | Requirement | Target | Implementation Constraint | NFR Ref |
|----|-------------|--------|--------------------------|---------|
| TR-008 | Cloud Run auto-scaling | 0→50 instances/service | CPU scale-out at 70%; min-instances=1 for API + SignalR hub; min-instances=0 for analytics | NFR-010 |
| TR-009 | DB connection management | ≤500 concurrent connections | PgBouncer sidecar on API service; pool_mode=transaction; max_client_conn=500 | NFR-005 |
| TR-010 | Read replica routing | 100% dashboard GETs | SQLAlchemy read/write session router; materialised views refresh every 60s | ADR-006 |
| TR-011 | Pub/Sub throughput | ≥500,000 messages/day | max_messages=100 on pull subscriptions; flow control enabled | NFR-012 |
| TR-012 | Storage auto-scaling | 100 GB/month | Cloud SQL storage auto-increase; Cloud Storage lifecycle: Nearline after 90 days | NFR-013 |

### 5.3 Availability Technical Requirements

| ID | Requirement | Target | Implementation Constraint | NFR Ref |
|----|-------------|--------|--------------------------|---------|
| TR-013 | Multi-zone deployment | 99.9% uptime | Cloud Run region `us-central1` multi-AZ; Cloud Run distributes automatically | NFR-020 |
| TR-014 | Cloud SQL HA | RPO <15 min, RTO <1 hour | Cloud SQL HA (regional instance); automated backups every 4h; PITR enabled (7-day window) | NFR-022, NFR-023 |
| TR-015 | Pub/Sub DLQ | Zero message loss | DLQ on all agent subscriptions; max_delivery_attempts=5; DLQ triggers PagerDuty P1 alert | NFR-042 |
| TR-016 | Health checks | <30s failure detection | Liveness: `GET /health` every 10s; Readiness: `GET /ready` every 5s | NFR-041 |
| TR-017 | Graceful shutdown | Zero in-flight loss | SIGTERM handler drains requests (max 30s); Pub/Sub `nack()` on shutdown for redelivery | TR-016 |

### 5.4 Infrastructure Technical Requirements

| ID | Requirement | Constraint |
|----|-------------|------------|
| TR-018 | 100% IaC | All GCP resources in Terraform modules; no console-provisioned resources |
| TR-019 | Container image security | Artifact Registry scan on every push; Cloud Build rejects CRITICAL CVEs; base: `python:3.12-slim` |
| TR-020 | CI/CD automation | Cloud Build trigger on main merge; ≥80% unit test coverage required; canary deploy (10% traffic → auto-promote) |
| TR-021 | Zero hardcoded secrets | All secrets in GCP Secret Manager; mounted as env vars via Secret Manager bindings |
| TR-022 | VPC isolation | Cloud SQL on private IP; Cloud Run uses VPC connector; only API Gateway has external ingress |

---

## 6. Data Architecture Requirements (DR)

### 6.1 Database Schema Design

| ID | Requirement | Detail | Ref |
|----|-------------|--------|-----|
| DR-001 | Schema version control | All DDL via Alembic migrations; run as Cloud Build pre-deploy step; no manual schema changes in production | TR-018 |
| DR-002 | PHI field encryption | Columns: `patient.first_name`, `last_name`, `dob`, `phone`, `email`, `mrn` (deterministic AES-256-GCM for indexed lookups), `document.content` — SQLAlchemy TypeDecorator; key from Secret Manager | BR-020, ADR-007 |
| DR-003 | Audit log immutability | `audit_log`: PostgreSQL row security `DENY DELETE, UPDATE`; no application role has DELETE privilege; nightly export to Cloud Storage WORM bucket | BR-023, SEC-006 |
| DR-004 | Encounter indexing | Composite index `(patient_id, admit_date DESC)`; index `(unit, status)` for bed board; index `(risk_tier, status)` for risk dashboard | TR-001 |
| DR-005 | Soft deletes | No hard deletes on patient/encounter; `deleted_at` column; default query scope filters `deleted_at IS NULL` | BR-022 |
| DR-006 | Data retention automation | pg_cron job: archive encounters `discharge_date < NOW() - INTERVAL '7 years'` to Cloud Storage; audit_logs retained 6 years | BR-022, BR-023 |
| DR-007 | Materialised views | `mv_bed_board` (60s refresh); `mv_risk_dashboard` (5 min refresh); `mv_kpi_daily` (nightly refresh) | ADR-006 |

### 6.2 Data Flow Design

```
INGEST PATH (Write):
EHR ──MLLP──► HL7 Listener ──► Pub/Sub ──► Coordinator Agent
                                                │
                                                ▼
                                          FastAPI Write API
                                                │
                                                ▼
                                        Cloud SQL Primary (ACID)
                                                │ (WAL replication)
                                                ▼
QUERY PATH (Read):                      Cloud SQL Read Replica
Angular Dashboard ──GET──► FastAPI Read API ──► Materialised Views

AUDIT PATH:
All PHI access ──► audit_log table (append-only)
              ──► Cloud Logging (structured, no PHI)
              ──► Cloud Storage WORM bucket (nightly)

FHIR DATA PATH:
Agent ──HTTPS──► FHIR R4 API ──► Pydantic model ──► Agent memory only
(FHIR data NOT persisted to SmartHandoff DB — transient per task)
```

### 6.3 Data Storage Requirements

| ID | Entity | Storage | Retention | Access Pattern |
|----|--------|---------|-----------|----------------|
| DR-010 | Encounter records | Cloud SQL Primary | 7 years, then archive | Write during ADT; read by dashboard |
| DR-011 | Audit logs | Cloud SQL (append-only) + WORM bucket | 6 years minimum | Write-only by middleware; read by compliance |
| DR-012 | Agent task records | Cloud SQL Primary | 2 years | Write per task; read by dashboard |
| DR-013 | AI-generated documents | Cloud SQL Primary (encrypted) | 7 years with encounter | Written once; read by review UI + portal |
| DR-014 | ML model artifacts | Cloud Storage (`ml-models/`) | 3 versions retained | Read at agent startup |
| DR-015 | HL7 raw message archive | Cloud Storage (HIPAA CMEK bucket) | 7 years | Write-once on ingest; read for audit |
| DR-016 | Chatbot transcripts | Cloud SQL (encrypted, encounter-linked) | 7 years with encounter | Write per message; read by care team |
| DR-017 | Analytics snapshots | BigQuery (de-identified) | Indefinite | Write nightly; read by analytics |

### 6.4 Data Quality Requirements

| ID | Requirement | Implementation | SRS Ref |
|----|-------------|---------------|---------|
| DR-020 | MRN deduplication | Unique constraint on `patient.mrn`; deterministic encryption enables encrypted-field unique index | DR-002 |
| DR-021 | FHIR data validation | `fhir.resources` validates all FHIR resource types on ingest; malformed resources rejected | FR-003 |
| DR-022 | HL7 message idempotency | MSH-10 message ID in `adt_event.source_message_id` with unique constraint; duplicates ACK'd and discarded | FR-001 |
| DR-023 | Encounter state machine | `encounter.status` transitions enforced at API layer: `REGISTERED → ADMITTED → TRANSFERRED → DISCHARGED`; invalid transitions return 409 | FR-002, FR-006 |
| DR-024 | PHI completeness | Pydantic models enforce required PHI fields (first_name, last_name, dob, mrn) at API boundary | FR-003 |

---

## 7. Architectural Integration Requirements (AIR)

### 7.1 HL7 MLLP Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-001 | MLLP listener resilience | TCP port 2575 via internal load balancer; ACK (AA) within 200ms; NACK (AE) on parse failure | FR-001 |
| AIR-002 | HL7 message validation | Mandatory: MSH, EVN, PID; PV1 required for A01/A02/A03; unknown event types NACK'd | FR-002, FR-003 |
| AIR-003 | HL7 raw message archival | Every raw message written to Cloud Storage before ACK; path: `hl7-archive/{year}/{month}/{day}/{msg-id}.hl7` | DR-015, BR-023 |
| AIR-004 | MLLP connection management | TCP keep-alive; max 50 concurrent connections; idle timeout 300s; asyncio connection pool | TR-005 |

### 7.2 FHIR R4 Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-010 | FHIR authentication | OAuth 2.0 client credentials (SMART on FHIR); access token cached with 60s expiry buffer | SEC-001 |
| AIR-011 | FHIR resilience | httpx async with exponential backoff (3 attempts: 1s/2s/4s); circuit breaker (10 failures/60s → open 120s) | TR-001 |
| AIR-012 | FHIR data not persisted | FHIR resource data held in agent memory per task only; never written to SmartHandoff DB (Constraint C-03) | C-03 |
| AIR-013 | FHIR rate limiting | 100 req/min per agent instance (token bucket); exceeding rate triggers exponential backoff | TR-001 |
| AIR-014 | FHIR patient resolution | Patient resolved via MRN in `Patient.identifier`; fallback to name+birthDate; unresolvable creates partial encounter | FR-003 |

### 7.3 Vertex AI / LLM Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-020 | Structured LLM output | `response_mime_type="application/json"` with Pydantic schema validation; malformed output retried (max 2) then template fallback | TR-004 |
| AIR-021 | PHI in LLM prompts | Minimum-necessary principle in prompt templates; no PHI in logging or telemetry | BR-021, PRV-001 |
| AIR-022 | LLM timeout and fallback | Hard timeout: 25s; template fallback at 28s; flagged in document metadata as `generation_type: TEMPLATE` | TR-004 |
| AIR-023 | LLM cost control | Token usage → Cloud Monitoring custom metric `vertex_ai_token_usage`; daily spend alert via Secret Manager threshold | A-06 |
| AIR-024 | Chatbot context window | System (2K) + discharge summary (4K max) + conversation history (2K) = 8K total; history pruned FIFO | FR-061 |

### 7.4 Identity Provider Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-030 | OIDC discovery | JWKS endpoint cached with 1-hour TTL at startup | SEC-001 |
| AIR-031 | JWT claims mapping | Required: `sub`, `email`, `roles[]`, `iat`, `exp`; missing claims → 401 | SEC-002 |
| AIR-032 | SCIM provisioning | User provisioned via SCIM 2.0; deprovisioning immediately revokes JWTs via token blocklist (Cloud Memorystore) | UC-016 |
| AIR-033 | MFA enforcement | Backend validates `amr` claim includes `mfa` for all staff roles | SEC-001 |

### 7.5 Notification Services

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-040 | Notification dispatch | Notification Service reads from `notification-requests` Pub/Sub topic; idempotency key prevents duplicates | FR-051 |
| AIR-041 | SMS delivery tracking | Twilio webhook updates delivery status; failed deliveries retried 3× with exponential backoff | FR-051 |
| AIR-042 | Email templates | SendGrid Dynamic Templates for all email types; versioned in source control as JSON | FR-051 |
| AIR-043 | OTP authentication | 6-digit OTP; 10-minute expiry; hash stored (not plaintext); rate-limited 5 OTPs/phone/hour | SEC-003 |

### 7.6 Drug Interaction Database

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-050 | Drug interaction API | RxNav Interaction API primary; OpenFDA fallback; results cached 24h per drug pair in Redis | FR-031 |
| AIR-051 | Severity mapping | HIGH (contraindicated/major) → immediate pharmacist alert; MEDIUM/LOW → logged only | FR-031, FR-035 |
| AIR-052 | Offline fallback | Both APIs unavailable → flag reconciliation incomplete; pharmacist alerted; discharge not blocked | FR-031 |

---

## 8. Security Architecture

### 8.1 Zero-Trust Service Mesh

```
EXTERNAL                     INTERNAL (VPC)
────────                     ─────────────
Browser/Mobile               Cloud Run Services
    │                            │ Service Account IAM
    │ HTTPS/TLS 1.3              │ (Workload Identity)
    ▼                            │ No public IPs — VPC internal only
Cloud Armor WAF                  │
(OWASP rules + rate limit)       │
    │                            ▼
Load Balancer ──────────► API Gateway (FastAPI)
(TLS termination)         JWT verified ──► RBAC
                                │
                          VPC Connector
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
       Cloud SQL           Pub/Sub          Secret Manager
       (Private IP)        (HMAC auth)      (IAM-scoped)
       CMEK + row          VPC service      Key rotation
       security            endpoint         enabled
```

### 8.2 Authentication Flow

**Staff Login:**
```
Browser → SSO OIDC + MFA → ID Token
Angular → POST /api/v1/auth/token
FastAPI → Validate OIDC signature → Extract roles → App JWT (15min, in-memory)
Every request: Authorization: Bearer {jwt} → role-scoped DB query
```

**Patient Portal:**
```
Patient receives SMS portal link → /portal?token={portal-token}
FastAPI validates portal-token (signed, 24h, encounter-scoped)
Patient requests OTP via Twilio Verify → FastAPI validates
Patient JWT issued (encounter-scoped, 60min, own data only)
```

### 8.3 RBAC Permission Matrix

| Resource | Admin | Physician | Nurse | Pharmacist | BedManager | Patient |
|----------|-------|-----------|-------|------------|------------|---------|
| All patients | ✓ | Own | Unit | ✗ | ✗ | ✗ |
| Patient detail | ✓ | ✓ | Unit | Meds only | ✗ | Own only |
| Documents (read) | ✓ | ✓ | ✓ | ✗ | ✗ | Own only |
| Documents (approve) | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Medication records | ✓ | ✓ | Read | ✓ | ✗ | Own summary |
| Bed board | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Analytics | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Audit logs | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| User management | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |

### 8.4 PHI Protection Layers

| Layer | Control | Technology |
|-------|---------|-----------|
| Transport | TLS 1.3 | Cloud Run ingress + Cloud Armor |
| Application | JWT scope validation | FastAPI dependency injection |
| ORM | AES-256-GCM field encryption | SQLAlchemy TypeDecorator + Secret Manager |
| Database | Block-level CMEK | Cloud SQL CMEK |
| Backup | Encrypted backup files | Cloud Storage CMEK |
| Logs | PHI stripped before emit | Log sanitisation middleware |
| Agent prompts | Minimum-necessary PHI | Prompt template design guardrails |
| Audit | Immutable access log | PostgreSQL row security + WORM bucket |

---

## 9. Deployment Architecture

### 9.1 GCP Service Topology

```
GCP PROJECT: smarthandoff-prod | Region: us-central1 (multi-AZ)
┌─────────────────────────────────────────────────────────────┐
│  VPC: smarthandoff-vpc (10.0.0.0/16)                        │
│                                                             │
│  Subnet: services (10.0.1.0/24)                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Cloud Run (internal ingress, VPC connector)        │   │
│  │  api-gateway │ hl7-listener │ agents (×6) │ notif   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Subnet: data (10.0.2.0/24)                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Cloud SQL Primary (10.0.2.10) + Replica (HA)       │   │
│  │  Cloud Memorystore Redis (10.0.2.20)                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

External (Global):
Cloud Storage (Angular PWA) → Cloud CDN → Cloud Armor → Cloud LB → API Cloud Run
```

### 9.2 Cloud Run Service Configuration

| Service | Min Inst | Max Inst | CPU | Memory | Concurrency |
|---------|----------|----------|-----|--------|-------------|
| api-gateway | 2 | 20 | 2 vCPU | 2 GB | 100 |
| hl7-listener | 1 | 10 | 1 vCPU | 512 MB | 50 |
| coordinator-agent | 1 | 10 | 2 vCPU | 2 GB | 20 |
| docs-agent | 1 | 10 | 2 vCPU | 4 GB | 5 |
| medrecon-agent | 1 | 10 | 2 vCPU | 2 GB | 10 |
| bed-mgmt-agent | 1 | 5 | 1 vCPU | 1 GB | 20 |
| followup-agent | 1 | 10 | 1 vCPU | 1 GB | 20 |
| comms-agent | 1 | 10 | 2 vCPU | 2 GB | 10 |
| ml-inference | 1 | 5 | 2 vCPU | 2 GB | 50 |
| notification-svc | 1 | 5 | 1 vCPU | 512 MB | 50 |

### 9.3 CI/CD Pipeline

```
Push to main → Cloud Build Pipeline:
  Step 1: Lint + SAST (ruff, bandit, pip-audit, eslint)
  Step 2: Unit Tests (pytest ≥80% coverage + Jest)
  Step 3: Container Build (Docker → Artifact Registry)
  Step 4: Vulnerability Scan (reject if CRITICAL CVE)
  Step 5: Integration Tests (staging Cloud SQL + Pub/Sub)
  Step 6: Canary Deploy (10% traffic — 15 min observation)
  Step 7: Auto-promote (if p95<500ms and error rate<1%)
         Auto-rollback (if thresholds breached)
```

---

## 10. Cross-Cutting Concerns

### 10.1 Observability Design

| Pillar | Technology | Key Signals |
|--------|-----------|-------------|
| Metrics | Cloud Monitoring | `adt_events_processed`, `agent_task_duration`, `vertex_ai_token_usage`, `doc_gen_latency_p95` |
| Logs | Cloud Logging (structured JSON) | `trace_id`, `span_id`, `service`, `encounter_id`, `event_type` — PHI excluded |
| Traces | Cloud Trace (OpenTelemetry) | Spans: FHIR fetch, LLM call, DB query, SignalR push; correlated via `X-Cloud-Trace-Context` |
| Alerts | Cloud Monitoring | P1: API error rate >1%; ADT lag >10s; SQL replication lag >30s; P2: Agent task failure >5%; P3: DLQ >0 |

### 10.2 Error Handling Strategy

| Error | Strategy |
|-------|----------|
| HL7 parse failure | NACK to EHR; archive message; structured log; alert |
| FHIR timeout | Exponential backoff (3 attempts); circuit breaker; partial encounter |
| Vertex AI timeout | 25s hard timeout; template fallback at 28s; flagged in metadata |
| Agent task failure | Pub/Sub nack → redelivery (max 5); DLQ → PagerDuty P1 |
| DB write failure | Transaction rollback; retry once; 503 + PagerDuty P1 on second failure |
| JWT invalid | 401 with `WWW-Authenticate: Bearer`; no internal error detail |
| Rate limit exceeded | 429 with `Retry-After` header; logged (no PHI) |
| Drug interaction API down | Incomplete flag; pharmacist alert; AIR-052 graceful degradation |

### 10.3 Caching Strategy

| Target | Technology | TTL | Key Pattern |
|--------|-----------|-----|-------------|
| Drug interaction results | Redis | 24h | `drug-interaction:{rxcui1}:{rxcui2}` |
| FHIR OIDC JWKS | In-memory per instance | 1h | N/A |
| Token blocklist | Redis | JWT expiry | `blocklist:{jti}` |
| Bed board view | PostgreSQL matview | 60s | Scheduled + event-triggered |
| KPI view | PostgreSQL matview | 5 min | Scheduled pg_cron |
| Angular assets | Cloud CDN | 1 year | Content-hash filenames |
| Patient instructions | Angular Service Worker | 30 days post-discharge | SW update on deploy |

---

## 11. Non-Functional Requirement Validation

| NFR ID | Target | Architecture Solution | Status |
|--------|--------|----------------------|--------|
| NFR-001 | <2s page load | Cloud CDN + lazy loading + <500KB bundle | ✓ Met |
| NFR-002 | <500ms API p95 | FastAPI async + read replica + indexed queries | ✓ Met |
| NFR-003 | <5s ADT processing | MLLP 200ms ACK + Pub/Sub async + agent min-instances=1 | ✓ Met |
| NFR-004 | <30s doc generation | Vertex AI streaming + 25s timeout + template fallback | ✓ Met |
| NFR-005 | 500 concurrent users | Cloud Run auto-scale + PgBouncer + SignalR group broadcast | ✓ Met |
| NFR-006 | <1s SignalR latency | Hub min-instances=2 + MessagePack protocol | ✓ Met |
| NFR-010 | 5,000 events/day | Pub/Sub managed throughput + Cloud Run scale-out | ✓ Met |
| NFR-020 | 99.9% uptime | Cloud Run multi-AZ + Cloud SQL HA | ✓ Met |
| NFR-022 | RTO <1 hour | Cloud SQL HA failover <60s | ✓ Met |
| NFR-023 | RPO <15 min | Cloud SQL PITR (continuous WAL) | ✓ Met |
| NFR-034 | WCAG 2.1 AA | Angular Material + axe-core CI check | ✓ Met |
| NFR-041 | MTTR <30 min | Cloud Run auto-restart + health probes <30s detection | ✓ Met |
| NFR-042 | Zero data loss | Cloud SQL WAL + ACID + Pub/Sub guaranteed delivery | ✓ Met |
| NFR-043 | 4h backup | Cloud SQL automated backup (hourly PITR) | ✓ Exceeded |
| SEC-004 | AES-256 at rest | Cloud SQL CMEK + SQLAlchemy field-level encryption | ✓ Met (2 layers) |
| SEC-005 | TLS 1.3 | Cloud Run enforces TLS 1.3 minimum | ✓ Met |

---

## 12. Architecture Risk Register

| ID | Risk | Probability | Impact | Mitigation |
|----|------|-------------|--------|------------|
| AR-001 | Vertex AI quota exceeded at peak discharge | Medium | High | Token monitoring + budget alerts; LLaMA 3 fallback ready |
| AR-002 | EHR HL7 MLLP feed unavailable | Medium | Critical | HL7 DLQ + replay; FHIR polling fallback; Hospital IT alert |
| AR-003 | FHIR R4 endpoint unavailable | Medium | High | Circuit breaker; partial encounter; manual data entry UI |
| AR-004 | Cloud SQL primary failure | Low | Critical | Cloud SQL HA failover <60s; PITR tested quarterly |
| AR-005 | Drug interaction API (RxNav) outage | Medium | High | OpenFDA fallback; 24h Redis cache; AIR-052 graceful mode |
| AR-006 | Angular bundle size degrading load | Medium | Medium | Webpack Bundle Analyzer in CI; PR blocked if chunk >500KB |
| AR-007 | PHI leakage via LLM prompt logs | Low | Critical | Log sanitiser middleware; Vertex AI prompt logging disabled; quarterly HIPAA audit |
| AR-008 | Pub/Sub ordering violations causing duplicate agent triggers | Low | High | Ordering keys per encounter ID; AgentTask idempotency check |
| AR-009 | Scikit-learn model accuracy degradation | Medium | Medium | Monthly drift monitoring; retrain trigger at <75% accuracy |
| AR-010 | Identity Provider SSO outage | Low | Critical | Emergency break-glass local auth accounts; procedure in runbook |

---

## 13. Glossary

| Term | Definition |
|------|------------|
| ADR | Architecture Decision Record — captures a key decision, its context, and consequences |
| CQRS | Command Query Responsibility Segregation — separate write and read models |
| CMEK | Customer-Managed Encryption Key — GCP encryption with customer-controlled keys |
| DLQ | Dead Letter Queue — holds messages that failed processing after maximum retries |
| MLLP | Minimal Lower Layer Protocol — TCP transport for HL7 v2 messages |
| PITR | Point-in-Time Recovery — restore database to any point within retention window |
| PWA | Progressive Web App — web application with offline support and installability |
| SignalR | WebSocket abstraction with HTTP fallback for real-time push messaging |
| SMART on FHIR | OAuth2-based FHIR API authentication standard |
| TR | Technical Requirement — architecture-level implementation constraint |
| DR | Data Architecture Requirement — data storage, flow, and quality constraint |
| AIR | Architectural Integration Requirement — external system integration contract |
| VPC | Virtual Private Cloud — isolated GCP network |
| WAF | Web Application Firewall — Cloud Armor OWASP rule set |
| WAL | Write-Ahead Log — PostgreSQL durability mechanism; basis for PITR |

---

*End of SmartHandoff Architecture Design Specification — Version 1.0 | Generated: 2026-07-13*
