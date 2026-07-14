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
│                             │                                   │                 │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architecture Decision Records (ADRs)

### ADR-001: Event-Driven Architecture via GCP Pub/Sub

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | ADT events arrive in bursts (bed changes, shift changes); agents must process independently without blocking intake |
| **Decision** | All ADT events published to GCP Pub/Sub `adt-events` topic; each agent type subscribes on a dedicated subscription with its own dead-letter queue |
| **Consequences** | (+) Agent failures don't block event intake; (+) horizontal agent scaling independent of API; (−) eventual consistency — dashboard reflects agent state, not real-time EHR state |
| **NFR Traceability** | NFR-003 (<5s processing), NFR-010 (scale to 5,000 events/day) |

### ADR-002: GCP Cloud Run for Stateless Service Hosting

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Constraint C-05 mandates GCP; variable ADT volume requires cost-efficient auto-scaling; no persistent state in agent containers |
| **Decision** | All backend services (API, HL7 Listener, individual agents) deployed as Cloud Run services with min-instances=1 for latency-sensitive paths |
| **Consequences** | (+) Auto-scaling 0→N within 10 seconds; (+) per-request billing; (−) cold-start latency risk on agents — mitigated by min-instances=1 |
| **NFR Traceability** | NFR-005 (500 concurrent), NFR-010 (10× scale), NFR-020 (99.9% uptime) |

### ADR-003: PostgreSQL (Cloud SQL) as System of Record

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | HIPAA requires ACID transactional writes, row-level encryption, and immutable audit logs; relational model fits domain entities |
| **Decision** | Cloud SQL PostgreSQL with CMEK encryption; separate `audit_log` table with append-only policy enforced by row security; read replicas for dashboard queries |
| **Consequences** | (+) HIPAA compliance via CMEK + WAL; (+) mature ACID guarantees; (−) horizontal write scaling requires sharding strategy in Phase 3 |
| **NFR Traceability** | NFR-042 (zero data loss), NFR-043 (4-hour backup), SEC-004 |

### ADR-004: LangChain + Vertex AI (Gemini) for Agent Orchestration

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Six agents require: LLM calls, tool use, structured output, and inter-agent communication; Vertex AI mandated for GCP alignment |
| **Decision** | LangChain as agent framework; Vertex AI Gemini 1.5 Pro as primary LLM; Scikit-learn models served as Cloud Run microservices for ML inference; fallback to template generation if Vertex AI unavailable |
| **Consequences** | (+) LangChain abstracts LLM provider — enables open-source fallback (Assumption A-06); (+) structured output enforced via Pydantic schemas; (−) Vertex AI token costs must be monitored |
| **NFR Traceability** | NFR-004 (<30s document generation), FR-020, FR-052 |

### ADR-005: Angular 17 PWA with SignalR for Real-Time UI

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Staff require real-time ADT feeds and agent status; patients require mobile-first portal without app installation |
| **Decision** | Single Angular 17 PWA with lazy-loaded feature modules per role; SignalR WebSocket hub for real-time push; service worker for offline caching of patient instructions |
| **Consequences** | (+) One codebase for staff dashboard and patient portal; (+) PWA installability for patients; (−) Angular bundle size requires aggressive lazy loading |
| **NFR Traceability** | NFR-001 (<2s page load), NFR-006 (<1s SignalR latency), NFR-033 (mobile) |

### ADR-006: CQRS Pattern for Dashboard Performance

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | Dashboard queries (risk scores, agent status, bed board) are read-heavy and aggregated; write path requires ACID guarantees |
| **Decision** | Commands (ADT processing, document approval) go through FastAPI write API → PostgreSQL primary; queries go through FastAPI read API → PostgreSQL read replica with materialised views |
| **Consequences** | (+) Read replica offloads dashboard queries; (+) materialised views pre-compute KPIs; (−) replication lag (typically <1s) must be acceptable for non-critical reads |
| **NFR Traceability** | NFR-002 (<500ms API p95), NFR-005 (500 concurrent users) |

### ADR-007: Field-Level PHI Encryption at ORM Layer

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Context** | HIPAA requires PHI encrypted at rest; Cloud SQL CMEK encrypts blocks but PHI also requires application-layer field encryption to prevent DB admin access |
| **Decision** | SQLAlchemy custom type decorators encrypt PHI fields (FirstName, LastName, DOB, Phone, Email, MRN, document Content) using AES-256-GCM with keys from GCP Secret Manager; Cloud SQL CMEK provides second encryption layer |
| **Consequences** | (+) Defense-in-depth: two encryption layers; (+) PHI never in plaintext in DB or logs; (−) encrypted fields not directly queryable — MRN uses deterministic encryption for lookups |
| **NFR Traceability** | SEC-004, BR-020, BR-021 |

---

## 3. System Component Design

### 3.1 Component Inventory

| Component | Type | Technology | Responsibility |
|-----------|------|------------|----------------|
| HL7 Listener | Cloud Run Service | Python + hl7apy | MLLP TCP ingestion → HTTP bridge → Pub/Sub publish |
| API Gateway | Cloud Run Service | Python FastAPI | REST API, JWT auth, RBAC enforcement, SignalR hub |
| Transition Coordinator Agent | Cloud Run Service | Python LangChain | Workflow orchestration, task dispatch, SLA tracking |
| Documentation Agent | Cloud Run Service | Python LangChain + Vertex AI | Discharge summary, patient instructions, completeness checks |
| Medication Reconciliation Agent | Cloud Run Service | Python LangChain + RxNav | Med list comparison, interaction detection, pharmacist alerts |
| Bed Management Agent | Cloud Run Service | Python + Scikit-learn | Bed board, discharge prediction, ED boarding alerts |
| Follow-up Care Agent | Cloud Run Service | Python LangChain + Scikit-learn | Risk scoring, appointment scheduling, reminder dispatch |
| Patient Communication Agent | Cloud Run Service | Python LangChain + Vertex AI | Chatbot, urgency detection, escalation routing |
| ML Inference Service | Cloud Run Service | Python FastAPI + Scikit-learn | Serve readmission risk and discharge time prediction models |
| Notification Service | Cloud Run Service | Python | Twilio SMS + SendGrid email dispatch with retry |
| Angular PWA | Cloud Storage + CDN | Angular 17 | Staff dashboard, patient portal, real-time updates |
| Cloud SQL (Primary) | Managed DB | PostgreSQL 15 | Transactional writes, CMEK encrypted, WAL enabled |
| Cloud SQL (Replica) | Managed DB | PostgreSQL 15 | Read queries, dashboard materialised views |
| GCP Pub/Sub | Managed Messaging | GCP Pub/Sub | ADT event bus, agent-to-agent messaging |
| GCP Secret Manager | Managed Secrets | GCP Secret Manager | API keys, encryption keys, service credentials |
| Cloud Armor | WAF/DDoS | GCP Cloud Armor | Rate limiting, OWASP rule set, geo-blocking |
| Cloud Monitoring | Observability | GCP Cloud Monitoring + Logging | Metrics, traces, structured logs, alerting |

### 3.2 Agent Architecture Detail

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AGENT SUBSYSTEM ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  GCP Pub/Sub                                                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Topic: adt-events                                           │   │
│  │                                                              │   │
│  │  Subscription per agent (with dead-letter queue):           │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │   │
│  │  │coordinator-  │ │docs-agent-   │ │medrecon-     │  ...   │   │
│  │  │sub           │ │sub           │ │agent-sub     │        │   │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘        │   │
│  └─────────┼────────────────┼────────────────┼────────────────┘   │
│            │                │                │                      │
│            ▼                ▼                ▼                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  AGENT CONTAINER PATTERN                     │   │
│  │                                                              │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  LangChain Agent (per container)                     │   │   │
│  │  │                                                      │   │   │
│  │  │  ┌────────────┐   ┌─────────────┐  ┌─────────────┐  │   │   │
│  │  │  │  Message   │   │  LangChain  │  │  Tool Set   │  │   │   │
│  │  │  │  Consumer  │──►│  Executor   │─►│  (FHIR,LLM, │  │   │   │
│  │  │  │  (Pub/Sub) │   │  + Prompt   │  │  DB, API)   │  │   │   │
│  │  │  └────────────┘   │  Templates  │  └──────┬──────┘  │   │   │
│  │  │                   └─────────────┘         │          │   │   │
│  │  │                                           ▼          │   │   │
│  │  │  ┌──────────────────────────────────────────────┐   │   │   │
│  │  │  │  Pydantic Output Schema (structured output)  │   │   │   │
│  │  │  └──────────────────────────┬───────────────────┘   │   │   │
│  │  └─────────────────────────────┼─────────────────────── │   │   │
│  │                                │                         │   │   │
│  │                                ▼                         │   │   │
│  │  ┌──────────────┐   ┌──────────────────┐                │   │   │
│  │  │  AgentTask   │   │  SignalR Hub     │                │   │   │
│  │  │  DB Write    │   │  (push to UI)    │                │   │   │
│  │  └──────────────┘   └──────────────────┘                │   │   │
│  └──────────────────────────────────────────────────────────┘   │   │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 API Layer Design

```
┌──────────────────────────────────────────────────────────────┐
│                   FASTAPI BACKEND STRUCTURE                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Routers (versioned: /api/v1/...)                            │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │
│  │ /auth       │ │ /encounters  │ │ /patients            │  │
│  │ /admin/users│ │ /documents   │ │ /medications         │  │
│  │ /admin/audit│ │ /tasks       │ │ /beds                │  │
│  └─────────────┘ └──────────────┘ └──────────────────────┘  │
│                                                              │
│  Middleware Stack (request order):                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  1. Cloud Armor (WAF — external)                    │    │
│  │  2. TLS Termination (Cloud Run ingress)             │    │
│  │  3. Rate Limiter (slowapi — 1000 req/min/user)      │    │
│  │  4. JWT Validator (python-jose)                     │    │
│  │  5. RBAC Enforcer (role claims → permission check)  │    │
│  │  6. PHI Log Sanitiser (strips PHI from access logs) │    │
│  │  7. HIPAA Audit Logger (structured, immutable)      │    │
│  │  8. Request Handler (router dispatch)               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  SignalR Hub: /hubs/dashboard                               │
│  Groups: encounter-{id}, unit-{unitId}, role-{roleName}     │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Frontend Module Architecture

```
smarthandoff-angular/
├── core/                          # Singleton services, guards, interceptors
│   ├── auth/                      # OAuthService, JwtInterceptor, AuthGuard
│   ├── signalr/                   # SignalRService (real-time hub connection)
│   ├── api/                       # Generated API client (openapi-generator)
│   └── audit/                     # Client-side audit event emitter
│
├── shared/                        # Reusable components, pipes, directives
│   ├── components/                # RiskBadge, AILabel, SkeletonLoader, Toast
│   └── pipes/                     # MaskMrn, ReadingLevel, RelativeTime
│
├── features/                      # Lazy-loaded feature modules (per role)
│   ├── dashboard/                 # FR-070–074: ADT feed, metrics, agent status
│   ├── patients/                  # FR-071: Patient list + detail
│   ├── medications/               # FR-030–035: Med reconciliation UI
│   ├── documents/                 # FR-020–024: Dual-pane review editor
│   ├── beds/                      # FR-040–043: Bed board
│   ├── analytics/                 # FR-073: KPI dashboards (Chart.js)
│   ├── patient-portal/            # FR-060–065: Patient instructions + chatbot
│   └── admin/                     # FR-074: User management, audit log
│
└── environments/                  # Environment config (dev/staging/prod)
```

---

## 4. Technology Stack

### 4.1 Technology Selection Matrix

| Layer | Technology | Version | Justification | NFR/FR Drivers |
|-------|-----------|---------|---------------|----------------|
| **Frontend Framework** | Angular | 17 | BRD-mandated; PWA support; TypeScript strict mode; lazy loading for performance | NFR-001, NFR-033 |
| **UI Component Library** | Angular Material | 17 | WCAG 2.1 AA built-in; consistent healthcare-grade components | NFR-034 |
| **Real-time (Client)** | @microsoft/signalr | 7.x | WebSocket with HTTP fallback; group-based broadcast for role filtering | NFR-006, FR-012 |
| **Charts** | Chart.js | 4.x | Lightweight; no D3 complexity for KPI dashboards | FR-073 |
| **PWA** | Angular Service Worker | 17 | Offline instruction caching for patients | A-04 (connectivity) |
| **Backend Framework** | Python FastAPI | 0.110+ | Async-native; OpenAPI spec auto-generation; Pydantic v2 validation | NFR-002 |
| **ASGI Server** | Uvicorn + Gunicorn | latest | Production-grade; multi-worker; Cloud Run compatible | NFR-005 |
| **ORM** | SQLAlchemy | 2.x | Async support; custom type decorators for PHI encryption | BR-020, ADR-007 |
| **DB Migration** | Alembic | latest | Version-controlled schema migrations | DR-001 |
| **Agent Framework** | LangChain | 0.2+ | Tool abstraction; Vertex AI integration; structured output | ADR-004 |
| **LLM** | Vertex AI Gemini 1.5 Pro | latest | GCP-native; 1M token context; JSON output mode | FR-020, FR-060 |
| **LLM Fallback** | LLaMA 3 (Cloud Run GPU) | 3.1 8B | Open-source fallback per Assumption A-06 | A-06 |
| **ML Framework** | Scikit-learn | 1.5+ | Readmission risk (LogisticRegression); LOS prediction (GradientBoosting) | FR-052, FR-040 |
| **ML Serving** | FastAPI (dedicated service) | 0.110+ | Lightweight REST inference endpoint for Scikit-learn models | FR-052 |
| **Drug Interaction DB** | RxNav / OpenFDA API | REST | NIH-maintained; free; covers major drug interactions | FR-031 |
| **HL7 Parsing** | hl7apy | 1.3.4 | Python HL7 v2.x parser; ADT segment support | FR-003 |
| **FHIR Client** | fhir.resources + httpx | latest | Typed FHIR R4 model classes; async HTTP client | FR-030 |
| **Authentication** | python-jose + Authlib | latest | JWT validation; OIDC token exchange | SEC-001 |
| **Message Bus** | GCP Pub/Sub | managed | Durable, ordered delivery; per-agent subscriptions with DLQ | ADR-001 |
| **Database** | Cloud SQL PostgreSQL | 15 | ACID; CMEK; read replicas; WAL for RPO <15min | ADR-003 |
| **Compute** | Cloud Run | managed | Auto-scaling; per-request billing; VPC connector for SQL | ADR-002 |
| **CDN / Static** | Cloud CDN + Cloud Storage | managed | Angular PWA hosting; global edge caching | NFR-001 |
| **Secret Management** | GCP Secret Manager | managed | API keys, encryption keys, DB credentials | SEC-004, ADR-007 |
| **WAF** | Cloud Armor | managed | OWASP Top 10 rules; rate limiting; DDoS protection | SEC-012 |
| **Observability** | Cloud Monitoring + Cloud Logging | managed | Structured logs; custom metrics; SLO tracking | NFR-020 |
| **Tracing** | Cloud Trace (OpenTelemetry) | managed | Distributed traces across agent chain | TR-010 |
| **SMS** | Twilio Programmable SMS | REST API | FR-051: Medication reminders; OTP auth | FR-051, SEC-003 |
| **Email** | SendGrid | REST API | FR-051: Email notifications and patient portal links | FR-051 |
| **Containerisation** | Docker | latest | Reproducible builds; Cloud Run deployment | TR-005 |
| **IaC** | Terraform | 1.7+ | GCP infrastructure as code; repeatable environments | TR-006 |
| **CI/CD** | Cloud Build + Cloud Deploy | managed | Build, test, canary deploy pipeline | TR-007 |

### 4.2 Technology Dependency Graph

```
Angular 17 PWA
    ├── @microsoft/signalr  ──► FastAPI SignalR Hub
    ├── openapi-generated client ──► FastAPI REST API
    └── Angular Service Worker (PWA offline cache)

FastAPI Backend
    ├── SQLAlchemy 2.x ──► Cloud SQL PostgreSQL 15
    ├── GCP Pub/Sub SDK ──► adt-events topic
    ├── python-jose ──► Identity Provider (OIDC)
    └── slowapi ──► Rate limiter

AI Agents (each a Cloud Run service)
    ├── LangChain 0.2+ ──► Vertex AI Gemini 1.5 Pro
    ├── fhir.resources ──► EHR FHIR R4 endpoint
    ├── hl7apy ──► HL7 v2.x message parser
    ├── Scikit-learn ──► ML Inference Service (Cloud Run)
    └── GCP Pub/Sub SDK ──► adt-events subscriptions

Notification Service
    ├── Twilio SDK ──► Twilio SMS API
    └── SendGrid SDK ──► SendGrid Email API
```

---

## 5. Technical Requirements (TR)

Technical requirements derived from NFRs and architectural decisions — each TR maps to one or more implementation constraints.

### 5.1 Performance Technical Requirements

| ID | Requirement | Target | Implementation Constraint | NFR Ref |
|----|-------------|--------|--------------------------|---------|
| TR-001 | API response time (p95) | <500ms | FastAPI async handlers; read replica for GET endpoints; connection pool size ≥20; avoid N+1 queries (SQLAlchemy `selectinload`) | NFR-002 |
| TR-002 | Angular initial page load | <2 seconds | Bundle size <500KB (main chunk); lazy-load all feature modules; preload critical CSS; serve from Cloud CDN edge | NFR-001 |
| TR-003 | SignalR push latency | <1 second | SignalR hub on Cloud Run min-instances=2; group-scoped broadcasts (not global); binary protocol (MessagePack) over JSON | NFR-006 |
| TR-004 | AI agent document generation | <30 seconds | Vertex AI streaming response; LangChain `streaming=True`; timeout=25s with template fallback at 28s | NFR-004 |
| TR-005 | ADT event ingestion throughput | ≥5,000 events/day (peak 10× burst) | Pub/Sub topic with 100 message ordering keys; HL7 Listener Cloud Run max-instances=10; async ACK after Pub/Sub publish confirmed | NFR-010 |
| TR-006 | Chatbot response time | <3 seconds | Gemini Flash model for chatbot (vs. Pro for summaries); context window limited to 8K tokens for patient scope | NFR-007, FR-062 |
| TR-007 | ML inference latency | <500ms | Scikit-learn models pre-loaded in memory (no cold-load per request); model artifact cached in Cloud Run container filesystem | FR-052, FR-040 |

### 5.2 Scalability Technical Requirements

| ID | Requirement | Target | Implementation Constraint | NFR Ref |
|----|-------------|--------|--------------------------|---------|
| TR-008 | Cloud Run auto-scaling | 0→50 instances per service | CPU threshold: scale-out at 70% utilisation; min-instances=1 for API and SignalR hub; min-instances=0 for analytics service | NFR-010, NFR-011 |
| TR-009 | Database connection management | ≤500 simultaneous DB connections | PgBouncer connection pooler sidecar on API service; pool_mode=transaction; max_client_conn=500 | NFR-005, NFR-010 |
| TR-010 | Read replica routing | 100% of dashboard GET requests | SQLAlchemy `execution_options(schema_translate_map=...)` with read/write session router; materialised views refreshed every 60 seconds | ADR-006 |
| TR-011 | Pub/Sub throughput | ≥500,000 messages/day | Pub/Sub managed throughput; set `max_messages=100` on pull subscriptions; enable flow control | NFR-012 |
| TR-012 | Storage auto-scaling | 100 GB/month target | Cloud SQL storage auto-increase enabled; Cloud Storage for audit log archival (WORM bucket); lifecycle policy: move to Nearline after 90 days | NFR-013 |

### 5.3 Availability Technical Requirements

| ID | Requirement | Target | Implementation Constraint | NFR Ref |
|----|-------------|--------|--------------------------|---------|
| TR-013 | Cloud Run multi-zone deployment | 99.9% uptime | Deploy to GCP region with multi-AZ (e.g., `us-central1`); Cloud Run distributes across zones automatically | NFR-020 |
| TR-014 | Cloud SQL HA configuration | RPO <15 min, RTO <1 hour | Cloud SQL with High Availability (regional instance); automated backups every 4 hours; PITR enabled (7-day window) | NFR-022, NFR-023, NFR-043 |
| TR-015 | Pub/Sub dead-letter queue | Zero message loss | DLQ configured on all agent subscriptions; max_delivery_attempts=5; DLQ messages trigger PagerDuty alert | NFR-042 |
| TR-016 | Health checks | <30s failure detection | Cloud Run liveness probe: `GET /health` every 10s; readiness probe: `GET /ready` every 5s; unhealthy instances evicted | NFR-041 |
| TR-017 | Graceful shutdown | Zero in-flight request loss | SIGTERM handler drains in-flight requests (max 30s); Pub/Sub `nack()` on shutdown so unprocessed messages redelivered | TR-016 |

### 5.4 Infrastructure Technical Requirements

| ID | Requirement | Target | Implementation Constraint | — |
|----|-------------|--------|--------------------------|---|
| TR-018 | Infrastructure as Code | 100% GCP resources in Terraform | All Cloud Run services, Cloud SQL, Pub/Sub, IAM, Secret Manager defined in Terraform modules; no console-provisioned resources | — |
| TR-019 | Container image security | Zero critical CVEs in production images | Artifact Registry vulnerability scanning on every push; Cloud Build rejects images with CRITICAL severity; base image: `python:3.12-slim` | SEC-013 |
| TR-020 | CI/CD pipeline | Automated build→test→deploy | Cloud Build trigger on main branch merge; unit tests (≥80% coverage) + integration tests must pass; canary deploy (10% traffic) before full rollout | TR-007 |
| TR-021 | Secrets management | Zero hardcoded credentials | All secrets in GCP Secret Manager; mounted as env vars in Cloud Run via Secret Manager bindings; no secrets in container images or version control | SEC-011 |
| TR-022 | VPC networking | No public DB exposure | Cloud SQL behind VPC; Cloud Run services use VPC connector (`10.8.0.0/28`); only API Gateway has external ingress | SEC-010 |

---

## 6. Data Architecture Requirements (DR)

### 6.1 Database Schema Design

| ID | Requirement | Detail | BR/NFR Ref |
|----|-------------|--------|-----------|
| DR-001 | Schema version control | All DDL managed via Alembic migrations; no manual schema changes in production; migrations run as Cloud Build step pre-deploy | TR-018 |
| DR-002 | PHI field encryption | Columns: `patient.first_name`, `last_name`, `dob`, `phone`, `email`, `mrn` (deterministic AES-256-GCM), `document.content` — encrypted via SQLAlchemy TypeDecorator using key from Secret Manager | BR-020, ADR-007 |
| DR-003 | Audit log immutability | `audit_log` table: PostgreSQL row security policy `DENY DELETE, UPDATE`; no application account has DELETE privilege; backed up to Cloud Storage WORM bucket nightly | BR-023, SEC-006 |
| DR-004 | Encounter indexing | Composite index on `(patient_id, admit_date DESC)` for patient history lookups; index on `(unit, status)` for bed board queries; index on `(risk_tier, status)` for risk dashboard | TR-001 |
| DR-005 | Soft deletes | No hard deletes on patient or encounter records; `deleted_at` timestamp column; active records filter via default query scope | BR-022 |
| DR-006 | Data retention automation | PostgreSQL scheduled job (pg_cron): archive encounters where `discharge_date < NOW() - INTERVAL '7 years'` to Cloud Storage; audit_logs retained 6 years | BR-022, BR-023 |
| DR-007 | Materialised views | `mv_bed_board`: real-time bed status (refresh every 60s); `mv_risk_dashboard`: patient risk tiers (refresh every 5 min); `mv_kpi_daily`: KPI aggregates (refresh nightly) | ADR-006, TR-010 |

### 6.2 Data Flow Design

```
┌──────────────────────────────────────────────────────────────────────┐
│                        DATA FLOW ARCHITECTURE                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  INGEST PATH (Write)                                                  │
│  ─────────────────                                                    │
│  EHR ──MLLP──► HL7 Listener ──► Pub/Sub ──► Coordinator Agent        │
│                                              │                        │
│                                              ▼                        │
│                                         FastAPI Write API             │
│                                              │                        │
│                                              ▼                        │
│                                    Cloud SQL Primary (ACID write)     │
│                                              │                        │
│                                         (WAL replication)             │
│                                              │                        │
│                                              ▼                        │
│  QUERY PATH (Read)                   Cloud SQL Read Replica           │
│  ─────────────────                           │                        │
│  Angular Dashboard ──GET──► FastAPI Read API ┘                        │
│                                    │                                  │
│                             Materialised Views                        │
│                         (mv_bed_board, mv_risk_dashboard)             │
│                                                                       │
│  AUDIT PATH                                                           │
│  ──────────                                                           │
│  All PHI access ──► audit_log table (append-only)                     │
│                 ──► Cloud Logging (structured, no PHI)                │
│                 ──► Cloud Storage WORM bucket (nightly export)        │
│                                                                       │
│  FHIR DATA PATH                                                       │
│  ──────────────                                                        │
│  Agent ──HTTPS──► FHIR R4 API ──► Pydantic model ──► Agent context   │
│  (data NOT persisted to SmartHandoff DB — used transiently per task)  │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.3 Data Storage Requirements

| ID | Requirement | Storage Target | Retention | Access Pattern |
|----|-------------|---------------|-----------|----------------|
| DR-010 | Encounter records | Cloud SQL Primary | 7 years active, then archive | Write-heavy during ADT events; read by dashboard |
| DR-011 | Audit logs | Cloud SQL (append-only) + Cloud Storage WORM | 6 years minimum | Write-only by middleware; read by compliance queries |
| DR-012 | Agent task records | Cloud SQL Primary | 2 years | Write per task; read by dashboard and monitor |
| DR-013 | AI-generated documents | Cloud SQL Primary (encrypted content column) | 7 years with encounter | Written once; read by review UI and patient portal |
| DR-014 | ML model artifacts | Cloud Storage bucket (`ml-models/`) | Per release; 3 versions retained | Read at agent startup; overwritten on model retrain |
| DR-015 | HL7 raw message archive | Cloud Storage (HIPAA bucket, CMEK) | 7 years | Write-once on ingest; read for audit/replay |
| DR-016 | Chatbot transcripts | Cloud SQL (encrypted, linked to encounter) | 7 years with encounter | Write per message; read by care team |
| DR-017 | Analytics snapshots | BigQuery (de-identified) | Indefinite | Write nightly from materialised views; read by analytics |

### 6.4 Data Quality Requirements

| ID | Requirement | Implementation | SRS Ref |
|----|-------------|---------------|---------|
| DR-020 | MRN deduplication | Unique constraint on `patient.mrn`; ingest pipeline checks for existing MRN before insert; deterministic encryption enables encrypted-field unique index | DR-002 |
| DR-021 | FHIR data validation | `fhir.resources` library validates all FHIR resource types on ingest; malformed resources rejected with structured error log | FR-003 |
| DR-022 | HL7 message idempotency | Message ID (MSH-10) stored in `adt_event.source_message_id` with unique constraint; duplicate messages ACK'd and discarded | FR-001 |
| DR-023 | Encounter state machine | `encounter.status` transitions enforced: `REGISTERED → ADMITTED → TRANSFERRED → DISCHARGED`; invalid transitions rejected with 409 Conflict | FR-002, FR-006 |
| DR-024 | PHI completeness validation | Pydantic models enforce required PHI fields (first_name, last_name, dob, mrn) with `field_validator`; incomplete records rejected at API boundary | FR-003 |

---

## 7. Architectural Integration Requirements (AIR)

### 7.1 HL7 MLLP Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-001 | MLLP listener resilience | HL7 Listener Cloud Run service binds TCP port 2575 via internal load balancer; MLLP ACK (AA = Application Accept) sent within 200ms of message receipt; NACK (AE) on parse failure | FR-001 |
| AIR-002 | HL7 message validation | Mandatory segments: MSH, EVN, PID; PV1 required for A01/A02/A03; rejection of unknown event types with NACK and structured log | FR-002, FR-003 |
| AIR-003 | HL7 raw message archival | Every raw HL7 message written to Cloud Storage (HIPAA bucket) before ACK — guarantees replay capability; path: `hl7-archive/{year}/{month}/{day}/{message-id}.hl7` | DR-015, BR-023 |
| AIR-004 | MLLP connection management | TCP keep-alive enabled; max 50 concurrent MLLP connections; idle timeout 300 seconds; connection pool managed by asyncio | TR-005, NFR-005 |

### 7.2 FHIR R4 Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-010 | FHIR authentication | OAuth 2.0 client credentials flow (SMART on FHIR); access token cached with 60-second expiry buffer; token refresh via Authlib | SEC-001 |
| AIR-011 | FHIR resource fetching | Async HTTP client (httpx) with retry (exponential backoff: 3 attempts, 1s/2s/4s); circuit breaker pattern (10 failures in 60s → open for 120s) | TR-001 |
| AIR-012 | FHIR data not persisted | FHIR resource data held in agent memory per task only; never written to SmartHandoff DB (Phase 1 read-only mandate: Constraint C-03) | C-03, ADR-007 |
| AIR-013 | FHIR rate limiting | FHIR API calls rate-limited to 100 req/min per agent instance using token bucket; exceeding rate triggers exponential backoff | TR-001 |
| AIR-014 | FHIR patient resolution | Patient resolved via MRN in `Patient.identifier`; fallback to `Patient.name` + `birthDate` if MRN not found; unresolvable patient logs warning and creates partial encounter | FR-003 |

### 7.3 Vertex AI / LLM Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-020 | LLM structured output | All Vertex AI calls use `response_mime_type="application/json"` with Pydantic schema validation; malformed LLM output triggers retry (max 2) then template fallback | TR-004, FR-020 |
| AIR-021 | PHI in LLM prompts | PHI must be included in prompts only when necessary; minimum-necessary principle enforced in prompt templates; no PHI sent to logging or telemetry | BR-021, PRV-001 |
| AIR-022 | LLM timeout and fallback | Vertex AI call timeout: 25 seconds; at 28 seconds agent falls back to template-based document generation; fallback flagged in document metadata as `generation_type: TEMPLATE` | TR-004 |
| AIR-023 | LLM cost control | Token usage logged per request to Cloud Monitoring custom metric `vertex_ai_token_usage`; alert if daily spend exceeds budget threshold (configurable via Secret Manager) | A-06 |
| AIR-024 | Chatbot context window | Patient chatbot prompts include: system context (2K tokens) + patient discharge summary (4K tokens max) + conversation history (2K tokens) = 8K total; conversation history pruned FIFO | FR-061, TR-006 |

### 7.4 Identity Provider (SSO) Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-030 | OIDC discovery | FastAPI backend fetches OIDC discovery document at startup; JWKS endpoint cached with 1-hour TTL for JWT verification | SEC-001 |
| AIR-031 | JWT claims mapping | Required claims: `sub` (user ID), `email`, `roles` (array of role strings), `iat`, `exp`; invalid or missing claims return 401 | SEC-002 |
| AIR-032 | SCIM provisioning | User provisioning via SCIM 2.0 API (POST /api/v1/admin/users/provision); deprovisioning immediately revokes all active JWTs via token blocklist (Redis-compatible Cloud Memorystore) | UC-016 |
| AIR-033 | MFA enforcement | Backend validates `amr` claim includes `mfa` for all staff roles; patient OTP validated server-side via Twilio Verify before portal JWT issued | SEC-001 |

### 7.5 Notification Services Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-040 | Notification dispatch | Notification Service reads from Pub/Sub `notification-requests` topic; dispatches via Twilio (SMS) or SendGrid (email) based on `channel` field; idempotency key prevents duplicate sends | FR-051 |
| AIR-041 | SMS delivery tracking | Twilio webhook (`/webhooks/twilio/status`) updates notification delivery status in DB; failed deliveries retried 3× with exponential backoff; undeliverable after 3 failures alerts care team | FR-051 |
| AIR-042 | Email template management | SendGrid Dynamic Templates used for: patient portal link, appointment reminder, medication reminder, care team escalation; templates versioned in source control as JSON | FR-051 |
| AIR-043 | OTP authentication | Patient portal OTP generated server-side (6-digit, 10-minute expiry); delivered via Twilio Verify; OTP hash stored in DB (not plaintext); rate-limited to 5 OTP requests per phone per hour | SEC-003 |

### 7.6 Drug Interaction Database Integration

| ID | Requirement | Detail | SRS Ref |
|----|-------------|--------|---------|
| AIR-050 | Drug interaction API | RxNav Interaction API (`interaction.rxnav.nlm.nih.gov`) called per reconciliation; NLM OpenFDA Drug Interaction as fallback; results cached in Cloud Memorystore (Redis) for 24 hours per drug pair | FR-031 |
| AIR-051 | Interaction severity mapping | Severity levels mapped: HIGH (contraindicated, major), MEDIUM (moderate), LOW (minor); only HIGH triggers immediate pharmacist alert (FR-035); all levels recorded in reconciliation record | FR-031, FR-035 |
| AIR-052 | Offline interaction fallback | If both RxNav and OpenFDA unavailable: flag all reconciliations as "Interaction check incomplete — manual review required"; alert pharmacist; do not block discharge | FR-031 |

---

## 8. Security Architecture

### 8.1 Zero-Trust Service Mesh

```
┌──────────────────────────────────────────────────────────────────────┐
│                    ZERO-TRUST SECURITY PERIMETER                      │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  EXTERNAL                     INTERNAL (VPC)                         │
│  ────────                     ─────────────                          │
│                                                                       │
│  Browser/Mobile               Cloud Run Services                     │
│      │                            │                                  │
│      │ HTTPS/TLS 1.3              │ Service Account IAM              │
│      ▼                            │ (Workload Identity)              │
│  Cloud Armor WAF                  │                                  │
│  (OWASP rules +                   │ No public IPs                    │
│   rate limiting)                  │ VPC internal only                │
│      │                            │                                  │
│      ▼                            ▼                                  │
│  Load Balancer ──────────► API Gateway (FastAPI)                     │
│  (TLS termination)         JWT verified ──► RBAC                     │
│                                   │                                  │
│                            VPC Connector                             │
│                                   │                                  │
│                     ┌─────────────┼─────────────┐                   │
│                     │             │             │                    │
│                     ▼             ▼             ▼                    │
│              Cloud SQL      Pub/Sub        Secret Manager            │
│              (Private IP)   (VPC)          (IAM-scoped)             │
│              CMEK encrypt   Auth w/        Key version               │
│              Row security   HMAC-SHA256    rotation                  │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.2 Authentication & Authorization Flow

```
Staff Login Flow:
Browser → SSO (OIDC) → MFA → ID Token → Angular
    ↓
Angular → POST /api/v1/auth/token (id_token)
    ↓
FastAPI → Validate OIDC signature → Extract roles → Issue app JWT (15min)
    ↓
Angular stores JWT in memory (NOT localStorage — XSS protection)
    ↓
Every API request: Authorization: Bearer {jwt}
    ↓
FastAPI middleware: Verify JWT → Extract role → Check permission policy
    ↓
DB query filtered by role scope (row-level filtering)

Patient Portal Flow:
Patient receives SMS link → Opens /portal?token={portal-token}
    ↓
FastAPI validates portal-token (signed, 24h expiry, encounter-scoped)
    ↓
Patient requests OTP via Twilio Verify
    ↓
FastAPI validates OTP → Issues patient JWT (encounter-scoped, 60min)
    ↓
Patient JWT scope limited to own encounter data only
```

### 8.3 RBAC Permission Matrix

| Resource | Admin | Physician | Nurse | Pharmacist | BedManager | Patient |
|----------|-------|-----------|-------|------------|------------|---------|
| All patients list | ✓ | ✓ (own) | ✓ (own unit) | ✗ | ✗ | ✗ |
| Patient detail | ✓ | ✓ | ✓ (unit) | ✓ (meds only) | ✗ | Own only |
| Medication records | ✓ | ✓ | Read | ✓ | ✗ | Own summary |
| Documents (read) | ✓ | ✓ | ✓ | ✗ | ✗ | Own only |
| Documents (approve) | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Bed board | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Analytics | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Audit logs | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| User management | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Agent monitor | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |

### 8.4 PHI Protection Layers

| Layer | Control | Technology |
|-------|---------|-----------|
| Transport | TLS 1.3 | Cloud Run ingress + Cloud Armor |
| Application | JWT scope validation | FastAPI dependency injection |
| ORM | Field-level AES-256-GCM encryption | SQLAlchemy TypeDecorator |
| Database | Block-level CMEK encryption | Cloud SQL CMEK |
| Backup | Encrypted backup files | Cloud Storage CMEK |
| Logs | PHI stripped before logging | Log sanitisation middleware |
| Agent prompts | Minimum-necessary PHI inclusion | Prompt template design |
| Audit | Immutable access log | PostgreSQL row security |

---

## 9. Deployment Architecture

### 9.1 GCP Service Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GCP PROJECT: smarthandoff-prod                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Region: us-central1 (multi-AZ)                                     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  VPC: smarthandoff-vpc (10.0.0.0/16)                        │    │
│  │                                                             │    │
│  │  Subnet: services (10.0.1.0/24)                            │    │
│  │  ┌─────────────────────────────────────────────────────┐   │    │
│  │  │  Cloud Run Services (internal ingress)              │   │    │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐           │   │    │
│  │  │  │ API GW   │ │ HL7 Lst  │ │ Agents   │  ...      │   │    │
│  │  │  │ (2 min)  │ │ (1 min)  │ │ (1 min)  │           │   │    │
│  │  │  └──────────┘ └──────────┘ └──────────┘           │   │    │
│  │  └─────────────────────────────────────────────────────┘   │    │
│  │                                                             │    │
│  │  Subnet: data (10.0.2.0/24)                               │    │
│  │  ┌─────────────────────────────────────────────────────┐   │    │
│  │  │  Cloud SQL (Private IP: 10.0.2.10)                  │   │    │
│  │  │  Primary (us-central1-a) + Replica (us-central1-b)  │   │    │
│  │  │                                                     │   │    │
│  │  │  Cloud Memorystore Redis (10.0.2.20)                │   │    │
│  │  │  (Token blocklist + drug interaction cache)         │   │    │
│  │  └─────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  External (Global):                                                  │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────────────┐  │
│  │ Cloud CDN +  │  │  Cloud Armor  │  │  Cloud Load Balancer     │  │
│  │ Cloud Storage│  │  (WAF + DDoS) │  │  (HTTPS → API Cloud Run) │  │
│  │ (Angular PWA)│  └───────────────┘  └──────────────────────────┘  │
│  └──────────────┘                                                    │
│                                                                      │
│  Managed Services:                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Pub/Sub  │ │ Vertex AI│ │ Secret   │ │ Cloud    │ │ Cloud    │  │
│  │          │ │ (Gemini) │ │ Manager  │ │ Logging  │ │ Monitoring│ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 9.2 Cloud Run Service Configuration

| Service | Min Instances | Max Instances | CPU | Memory | Concurrency |
|---------|--------------|--------------|-----|--------|-------------|
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
Developer Push to main branch
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│                    CLOUD BUILD PIPELINE                       │
│                                                              │
│  Step 1: Lint + Security Scan                                │
│  ├── Python: ruff, bandit (SAST), pip-audit                  │
│  └── TypeScript: eslint, @angular-eslint                     │
│                                                              │
│  Step 2: Unit Tests (≥80% coverage required)                 │
│  ├── Backend: pytest + pytest-asyncio                        │
│  └── Frontend: Jest + Angular Testing Library                │
│                                                              │
│  Step 3: Build Container Images                              │
│  └── Docker build + push to Artifact Registry               │
│                                                              │
│  Step 4: Vulnerability Scan                                  │
│  └── Artifact Registry scan → reject if CRITICAL found       │
│                                                              │
│  Step 5: Integration Tests                                   │
│  └── pytest-asyncio against staging Cloud SQL + Pub/Sub      │
│                                                              │
│  Step 6: Cloud Deploy (Canary)                               │
│  ├── Deploy to 10% of Cloud Run traffic                      │
│  ├── Monitor error rate + p95 latency (15 minutes)           │
│  └── Auto-promote if healthy; auto-rollback if not           │
│                                                              │
│  Step 7: Full Rollout                                        │
│  └── Cloud Deploy promotes to 100% traffic                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 10. Cross-Cutting Concerns

### 10.1 Observability Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY STACK                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  METRICS (Cloud Monitoring)                                      │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ System: Cloud Run (request count, latency, CPU, mem)   │     │
│  │ Business: adt_events_processed, agent_task_duration,   │     │
│  │           readmission_risk_score_p95, doc_gen_latency   │     │
│  │ Custom: vertex_ai_token_usage, mllp_message_count       │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  LOGS (Cloud Logging — structured JSON, no PHI)                 │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Log fields: trace_id, span_id, service, user_id,       │     │
│  │             encounter_id, event_type, severity, message │     │
│  │ PHI fields: EXCLUDED (log sanitiser middleware)         │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  TRACES (Cloud Trace / OpenTelemetry)                           │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Trace: HL7 message → Pub/Sub → Agent → DB write        │     │
│  │ Spans: FHIR fetch, LLM call, DB query, SignalR push     │     │
│  │ Correlation: X-Cloud-Trace-Context header propagated    │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ALERTS (Cloud Monitoring Alerting)                             │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ P1: API error rate >1% (5-min window)                  │     │
│  │ P1: ADT event processing lag >10 seconds               │     │
│  │ P1: Cloud SQL replication lag >30 seconds              │     │
│  │ P2: Agent task failure rate >5%                        │     │
│  │ P2: Vertex AI error rate >10%                          │     │
│  │ P3: Pub/Sub DLQ message count >0                       │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Error Handling Strategy

| Error Category | Strategy | SRS Ref |
|----------------|----------|---------|
| HL7 parse failure | NACK sent to EHR; message archived; structured error log; alert raised | AIR-001 |
| FHIR timeout | Exponential backoff (3 attempts); circuit breaker after 10 failures; partial encounter record created | AIR-011 |
| Vertex AI timeout | 25-second hard timeout; fallback to template generation at 28 seconds; flagged in document metadata | AIR-022 |
| Agent task failure | Pub/Sub nack → redelivery (max 5 attempts); DLQ after max attempts; Supervisor alert via Cloud Monitoring | TR-015 |
| DB write failure | Transaction rollback; retry once with new connection; if retry fails: 503 response + PagerDuty P1 alert | TR-014 |
| JWT validation failure | 401 Unauthorised with `WWW-Authenticate: Bearer` header; no error detail exposed | SEC-011 |
| Rate limit exceeded | 429 Too Many Requests with `Retry-After` header; logged (not PHI) | SEC-012 |
| Drug interaction API unavailable | Flag reconciliation incomplete; pharmacist alert generated; AIR-052 fallback applied | AIR-052 |

### 10.3 Caching Strategy

| Cache Target | Technology | TTL | Invalidation |
|-------------|-----------|-----|--------------|
| Drug interaction results | Cloud Memorystore Redis | 24 hours | Key: `drug-interaction:{rxcui1}:{rxcui2}` |
| FHIR OIDC JWKS | In-memory (per instance) | 1 hour | Restart or manual flush |
| FHIR patient data | None (per-task only) | — | Data not persisted |
| Token blocklist (revoked JWTs) | Cloud Memorystore Redis | JWT expiry | Write on deprovisioning |
| Bed board materialised view | PostgreSQL (REFRESH MATERIALIZED VIEW) | 60 seconds | Event-triggered + scheduled |
| KPI materialised view | PostgreSQL | 5 minutes | Scheduled pg_cron job |
| Angular assets | Cloud CDN | 1 year (hashed filenames) | New deployment cache-busts via content hash |
| Patient portal instructions | Angular Service Worker | Until discharge date +30 days | SW update on version deploy |

### 10.4 Internationalisation (i18n)

| Concern | Implementation | SRS Ref |
|---------|---------------|---------|
| UI language | Angular i18n with XLIFF 2.0; locale determined by browser `Accept-Language`; staff UI: English only (Phase 1) | — |
| Document generation | Language determined by `Patient.communication.language` FHIR field; passed as parameter to Vertex AI prompt; 5 languages: `en`, `es`, `fr`, `zh`, `pt` | FR-022 |
| Patient portal | Angular i18n bundle per language; portal URL includes locale param (`/portal?lang=es`) | FR-022 |
| Date/time | All DB timestamps in UTC; display-layer conversion to local timezone via Angular `DatePipe` with hospital TZ config | — |

---

## 11. Non-Functional Requirement Validation

Validation of SRS NFRs against architectural decisions.

| NFR ID | Requirement | Target | Architecture Solution | Status |
|--------|-------------|--------|----------------------|--------|
| NFR-001 | Page load | <2s | Cloud CDN + Angular lazy loading + bundle <500KB | ✓ Met |
| NFR-002 | API p95 latency | <500ms | FastAPI async + read replica + connection pool + indexed queries | ✓ Met |
| NFR-003 | ADT event processing | <5s E2E | MLLP ACK in 200ms + Pub/Sub async + agent min-instances=1 | ✓ Met |
| NFR-004 | AI doc generation | <30s | Vertex AI streaming + 25s timeout + template fallback | ✓ Met |
| NFR-005 | 500 concurrent users | 500 sessions | Cloud Run auto-scale + PgBouncer pool + SignalR group broadcast | ✓ Met |
| NFR-006 | SignalR latency | <1s | SignalR hub min-instances=2 + MessagePack binary protocol | ✓ Met |
| NFR-010 | 5,000 ADT events/day | 5K/day | Pub/Sub managed throughput + Cloud Run scale-out | ✓ Met |
| NFR-011 | 100K patient records | 100K | Cloud SQL with storage auto-increase + read replicas | ✓ Met |
| NFR-020 | 99.9% uptime | 99.9% | Cloud Run multi-AZ + Cloud SQL HA + health checks | ✓ Met |
| NFR-022 | RTO | <1 hour | Cloud SQL HA failover (<60s) + Cloud Run auto-restart | ✓ Met |
| NFR-023 | RPO | <15 min | Cloud SQL PITR (continuous WAL) | ✓ Met |
| NFR-034 | WCAG 2.1 AA | AA | Angular Material built-in + axe-core CI check | ✓ Met |
| NFR-040 | MTBF | >720 hours | Cloud Run managed + Cloud SQL HA + Pub/Sub DLQ retry | ✓ Met |
| NFR-041 | MTTR | <30 min | Cloud Run auto-restart + health probes detect failures in <30s | ✓ Met |
| NFR-042 | Zero data loss | 0 loss | Cloud SQL WAL + ACID transactions + Pub/Sub guaranteed delivery | ✓ Met |
| NFR-043 | 4-hour backup | Every 4h | Cloud SQL automated backup (hourly PITR) | ✓ Exceeded |
| SEC-004 | AES-256 at rest | AES-256 | Cloud SQL CMEK + SQLAlchemy field-level encryption | ✓ Met (2 layers) |
| SEC-005 | TLS 1.3 in transit | TLS 1.3 | Cloud Run enforces TLS 1.3 minimum | ✓ Met |

---

## 12. Architecture Risk Register

| ID | Risk | Probability | Impact | Mitigation | Owner |
|----|------|-------------|--------|------------|-------|
| AR-001 | Vertex AI API quota exceeded during peak discharge times | Medium | High | Token usage monitoring + budget alerts; LLaMA 3 fallback deployment ready | AI/ML Team |
| AR-002 | EHR HL7 MLLP feed unavailable (Assumption A-01) | Medium | Critical | HL7 Listener DLQ + replay; FHIR polling fallback for Patient data; alert to Hospital IT | DevOps |
| AR-003 | FHIR R4 endpoint unavailable (Assumption A-02) | Medium | High | Circuit breaker with partial encounter creation; agent degraded mode with manual data entry UI | Backend Team |
| AR-004 | Cloud SQL primary failure | Low | Critical | Cloud SQL HA automatic failover (<60s); RPO <15min via PITR; tested quarterly | DevOps |
| AR-005 | Drug interaction API (RxNav) outage | Medium | High | OpenFDA fallback; local cache (24h TTL) serves recent lookups; AIR-052 graceful degradation | Backend Team |
| AR-006 | Angular bundle size growth degrading load time | Medium | Medium | Webpack Bundle Analyzer in CI; PR blocked if main chunk >500KB; periodic audit | Frontend Team |
| AR-007 | PHI leakage via LLM prompt logs | Low | Critical | Log sanitiser middleware strips all PHI fields; Vertex AI not configured to log prompts; quarterly HIPAA audit | Security Team |
| AR-008 | Pub/Sub message ordering violations causing duplicate agent triggers | Low | High | Message ordering keys per encounter ID; idempotency check on AgentTask before processing | Backend Team |
| AR-009 | Scikit-learn model accuracy degradation over time | Medium | Medium | Model performance monitored monthly; drift detection on readmission prediction accuracy; retrain trigger when accuracy drops <75% | AI/ML Team |
| AR-010 | Identity Provider SSO outage locks out all staff | Low | Critical | Emergency break-glass accounts (local DB auth) with strict audit logging; procedure documented in runbook | IT Director |

---

## 13. Glossary

| Term | Definition |
|------|------------|
| ADR | Architecture Decision Record — a document capturing a key architectural decision, its context, and consequences |
| CQRS | Command Query Responsibility Segregation — separate models for write (command) and read (query) operations |
| CMEK | Customer-Managed Encryption Key — Google Cloud encryption using keys controlled by the customer |
| DLQ | Dead Letter Queue — message queue holding messages that failed processing after maximum retries |
| MLLP | Minimal Lower Layer Protocol — TCP transport protocol for HL7 v2 messages |
| NFR | Non-Functional Requirement — system quality attributes (performance, availability, security) |
| PITR | Point-in-Time Recovery — ability to restore a database to any point within a retention window |
| PWA | Progressive Web App — web application with offline support and installability |
| SignalR | Microsoft WebSocket abstraction with HTTP fallback for real-time push messaging |
| SMART on FHIR | Substitutable Medical Applications and Reusable Technologies — OAuth2-based FHIR API auth standard |
| TR | Technical Requirement — architecture-level implementation constraint derived from NFRs |
| DR | Data Architecture Requirement — data storage, flow, and quality constraint |
| AIR | Architectural Integration Requirement — external system integration contract and constraint |
| VPC | Virtual Private Cloud — isolated GCP network for service-to-service communication |
| WAF | Web Application Firewall — Cloud Armor rule set blocking OWASP Top 10 attacks |
| WAL | Write-Ahead Log — PostgreSQL durability mechanism; basis for replication and PITR |

---

*End of SmartHandoff Architecture Design Specification — Version 1.0 | Generated: 2026-07-13*
