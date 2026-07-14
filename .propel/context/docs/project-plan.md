# SmartHandoff — Project Plan

> **Artifact:** project_plan | **Version:** 1.0 | **Status:** Draft
> **Date:** 2026-07-13 | **Upstream:** SRS v1.0, Design v1.0, Model v1.0, Epics v1.0 | **Workflow:** /create-project-plan
> **Project Manager:** SmartHandoff Project Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Scope](#2-project-scope)
3. [Team Composition & Roles](#3-team-composition--roles)
4. [Work Breakdown Structure (WBS)](#4-work-breakdown-structure-wbs)
5. [Effort Estimation](#5-effort-estimation)
6. [Sprint Plan](#6-sprint-plan)
7. [Milestone Schedule](#7-milestone-schedule)
8. [Cost Baseline](#8-cost-baseline)
9. [Risk Register](#9-risk-register)
10. [Dependency Matrix](#10-dependency-matrix)
11. [Governance & Communication Plan](#11-governance--communication-plan)
12. [Definition of Done & Quality Gates](#12-definition-of-done--quality-gates)
13. [Assumptions & Constraints](#13-assumptions--constraints)

---

## 1. Executive Summary

### 1.1 Project Overview

| Field | Value |
|-------|-------|
| **Project Name** | SmartHandoff — AI-Powered Care Transition Orchestrator |
| **Timeline** | 14 calendar days (2 × 1-week sprints) |
| **Team Size** | 6 developers |
| **Budget** | $79,200 (labour) + $3,500 (infrastructure MVP) = **$82,700** |
| **Delivery** | Angular 17 PWA + Python FastAPI + 6 LangChain agents on GCP |
| **Constraint** | MVP scope only; Must Have requirements only per Constraint C-01 |

### 1.2 Business Objectives Targeted

| Objective | Target | Epic Owner |
|-----------|--------|-----------|
| Reduce discharge documentation time by 60% | 30–60 min (from 2–4 hrs) | EP-004 |
| Medication error rate <10% | From 66% of ADEs | EP-005 |
| 30-day readmission rate reduced 25% | 15% (from 20%) | EP-007 |
| Patient satisfaction >85% | From 45% | EP-008, EP-010 |
| ED boarding time reduced 40% | <2 hours | EP-006 |

### 1.3 Delivery Confidence

| Area | Confidence | Risk Driver |
|------|------------|-------------|
| Infrastructure (EP-TECH, EP-DATA) | High | Standard GCP provisioning |
| Backend / HL7 / FHIR (EP-001, EP-002, EP-011) | Medium-High | EHR environment dependency |
| AI Agents (EP-003–008) | Medium | Vertex AI latency + LLM output quality |
| Frontend (EP-009, EP-010) | Medium-High | 14-day aggressive timeline for full PWA |
| ML Models (EP-006, EP-007) | Medium | Training data quality and availability |

---

## 2. Project Scope

### 2.1 In-Scope (MVP — Must Have)

| Category | Deliverables |
|----------|-------------|
| **Infrastructure** | GCP Cloud Run (10 services), Cloud SQL HA, Pub/Sub, VPC, Cloud Armor, Terraform IaC, CI/CD |
| **Backend** | FastAPI REST API + SignalR hub, HL7 MLLP listener, FHIR R4 client, HIPAA audit logging |
| **AI Agents** | Transition Coordinator, Documentation, Medication Reconciliation, Bed Management, Follow-up Care, Patient Communication |
| **ML Models** | Readmission risk LogisticRegression, Discharge time GradientBoosting |
| **Frontend** | Angular 17 PWA: staff dashboard + patient portal (11 screens) |
| **Security** | OIDC/MFA, RBAC (7 roles), PHI encryption, JWT blocklist, rate limiting |
| **Notifications** | Twilio SMS, SendGrid email, OTP authentication |

### 2.2 Out-of-Scope (Phase 1)

- EHR write-back / FHIR Appointment resource write
- Voice-enabled interfaces
- IoT bed sensors
- Insurance pre-authorization
- Multi-hospital federation
- Analytics BigQuery export (Should Have — deferred if timeline at risk)

### 2.3 MVP Acceptance Threshold

| Requirement | Gate |
|-------------|------|
| All Must Have FRs (55 of 75) | 100% implemented and passing acceptance tests |
| NFR-001 (<2s page load) | Lighthouse CI passing |
| NFR-003 (<5s ADT processing) | Integration test passing |
| SEC: HIPAA audit logging | All PHI access logged, PHI absent from Cloud Logging |
| NFR-020 (99.9% uptime) | Cloud Run HA + Cloud SQL HA provisioned |

---

## 3. Team Composition & Roles

### 3.1 Team Roster

| # | Role | Code | Key Responsibilities | Epic Ownership |
|---|------|------|---------------------|----------------|
| 1 | Senior Full-Stack Engineer (Backend Lead) | BE1 | FastAPI API, HIPAA middleware, FHIR client, HL7 listener | EP-001, EP-002, EP-011, EP-013 |
| 2 | Backend Engineer | BE2 | PostgreSQL schema, ORM, Pub/Sub integration, notification service | EP-DATA, EP-013, EP-012 (backend) |
| 3 | AI/ML Engineer (Agent Lead) | AI1 | LangChain base, Coordinator Agent, Documentation Agent, ML models | EP-003, EP-004, EP-007 |
| 4 | AI/ML Engineer | AI2 | Medication Reconciliation Agent, Bed Management Agent, Patient Comms Agent | EP-005, EP-006, EP-008 |
| 5 | Senior Frontend Engineer | FE1 | Angular PWA scaffold, care team dashboard, SignalR integration | EP-009, EP-011 (Angular auth) |
| 6 | DevOps / Platform Engineer | DO1 | Terraform IaC, CI/CD, Cloud Monitoring, security configs | EP-TECH, EP-009 (CI/CD), EP-012 (BigQuery) |

### 3.2 RACI Matrix

| Activity | BE1 | BE2 | AI1 | AI2 | FE1 | DO1 | Product Owner |
|----------|-----|-----|-----|-----|-----|-----|---------------|
| Architecture decisions | R | C | C | C | C | C | A |
| GCP provisioning | C | C | I | I | I | R | A |
| Database schema | R | R | I | I | I | C | A |
| Agent LangChain framework | C | I | R | C | I | I | A |
| Security / HIPAA compliance | R | C | C | C | C | R | A |
| Angular frontend | C | I | I | I | R | C | A |
| ML model training | I | I | R | R | I | I | A |
| Sprint demos | R | R | R | R | R | R | A |
| Go/No-Go decision | C | C | C | C | C | C | A |

*R = Responsible, A = Accountable, C = Consulted, I = Informed*

### 3.3 Working Agreements

- **Hours:** 8 hours/day, 5 days/week (Mon–Fri)
- **Standups:** 15 minutes daily at 09:00
- **Pair programming:** Mandatory for all security-related (EP-011) and HIPAA-related code
- **PR reviews:** Minimum 1 reviewer; security-related PRs require BE1 review
- **Branch policy:** Feature branches → `main` via PR; no direct commits to `main`
- **Definition of Done:** Applied to every story before marking complete (see §12)

---

## 4. Work Breakdown Structure (WBS)

### 4.1 WBS Summary

```
SmartHandoff MVP
├── 1. Infrastructure & Platform (EP-TECH)
│   ├── 1.1 Terraform IaC — GCP resources
│   ├── 1.2 CI/CD pipeline — Cloud Build + Cloud Deploy
│   ├── 1.3 Observability — Cloud Monitoring + Cloud Trace
│   └── 1.4 Secrets management — GCP Secret Manager
│
├── 2. Data Foundation (EP-DATA)
│   ├── 2.1 PostgreSQL schema — Alembic migrations
│   ├── 2.2 PHI field-level encryption — SQLAlchemy TypeDecorators
│   ├── 2.3 Audit log immutability — Row security + WORM backup
│   ├── 2.4 Materialised views — mv_bed_board, mv_risk_dashboard, mv_kpi_daily
│   └── 2.5 Data retention — pg_cron archival jobs
│
├── 3. HL7 ADT Event Ingestion (EP-001)
│   ├── 3.1 MLLP TCP listener
│   ├── 3.2 HL7 v2.x parser (all 8 event types)
│   ├── 3.3 Cloud Storage raw message archival
│   ├── 3.4 Pub/Sub publish with idempotency
│   └── 3.5 Cancellation event handling
│
├── 4. EHR / FHIR Integration (EP-002)
│   ├── 4.1 FHIR R4 async client + SMART on FHIR auth
│   ├── 4.2 Retry + circuit breaker + rate limiting
│   ├── 4.3 FHIR data transience enforcement
│   └── 4.4 Patient resolution (MRN + fallback)
│
├── 5. Security & HIPAA Compliance (EP-011)
│   ├── 5.1 OIDC SSO + MFA enforcement
│   ├── 5.2 HIPAA audit logging middleware
│   ├── 5.3 RBAC permission enforcement
│   ├── 5.4 JWT token blocklist + deprovisioning
│   └── 5.5 Security headers + rate limiting + input validation
│
├── 6. AI Agent Orchestration Framework (EP-003)
│   ├── 6.1 LangChain base agent class
│   ├── 6.2 Transition Coordinator Agent
│   ├── 6.3 SLA monitoring + supervisor escalation
│   ├── 6.4 SignalR real-time push
│   └── 6.5 DLQ configuration + graceful shutdown
│
├── 7. Documentation Agent (EP-004)
│   ├── 7.1 Discharge summary generation (Vertex AI)
│   ├── 7.2 Patient instructions (plain-language)
│   ├── 7.3 Multilingual translation (5 languages)
│   ├── 7.4 Dual-pane review UI
│   └── 7.5 Completeness validation
│
├── 8. Medication Reconciliation Agent (EP-005)
│   ├── 8.1 3-list comparison algorithm
│   ├── 8.2 Drug interaction detection (RxNav + Redis cache)
│   ├── 8.3 Duplicate + missing chronic med detection
│   ├── 8.4 Patient medication summary
│   └── 8.5 24-hour SLA escalation
│
├── 9. Bed Management Agent (EP-006)
│   ├── 9.1 Real-time bed board + ADT updates
│   ├── 9.2 ML discharge time prediction
│   ├── 9.3 ED boarding alert (2-hour threshold)
│   └── 9.4 Housekeeping notification
│
├── 10. Follow-up Care Agent (EP-007)
│   ├── 10.1 Readmission risk ML scoring
│   ├── 10.2 HIGH-risk care pathway activation
│   ├── 10.3 48-hour check-in scheduling
│   └── 10.4 Post-discharge concern escalation
│
├── 11. Patient Communication Agent (EP-008)
│   ├── 11.1 24/7 AI chatbot (Gemini Flash)
│   ├── 11.2 Urgency signal detection
│   ├── 11.3 Human escalation workflow
│   └── 11.4 Transcript storage (encrypted)
│
├── 12. Care Team Dashboard (EP-009)
│   ├── 12.1 Angular PWA scaffold + routing
│   ├── 12.2 ADT event feed + patient risk list
│   ├── 12.3 Physician document approval queue
│   ├── 12.4 Medication reconciliation queue (pharmacist)
│   └── 12.5 Agent activity monitor
│
├── 13. Patient Portal (EP-010)
│   ├── 13.1 OTP authentication flow
│   ├── 13.2 Discharge instructions display (multilingual)
│   ├── 13.3 PDF download
│   └── 13.4 Offline caching (Service Worker)
│
├── 14. Notification Infrastructure (EP-013)
│   ├── 14.1 SMS/email dispatch (Twilio + SendGrid)
│   ├── 14.2 OTP delivery (Twilio Verify)
│   └── 14.3 Delivery tracking + failure alerts
│
└── 15. Analytics & KPI Reporting (EP-012)
    ├── 15.1 KPI dashboard (Chart.js)
    ├── 15.2 CSV/PDF export
    └── 15.3 BigQuery de-identified export
```

### 4.2 WBS Story Point Summary

| WBS | Epic | Owner | Story Points | Priority |
|-----|------|-------|-------------|---------|
| 1 | EP-TECH | DO1 | 18 | Critical |
| 2 | EP-DATA | BE2 | 18 | Critical |
| 3 | EP-001 | BE1 | 16 | Critical |
| 4 | EP-002 | BE1 | 12 | Critical |
| 5 | EP-011 | BE1 + DO1 | 21 | Critical |
| 6 | EP-003 | AI1 + BE1 | 23 | High |
| 7 | EP-004 | AI1 | 24 | High |
| 8 | EP-005 | AI2 + BE1 | 21 | High |
| 9 | EP-006 | AI2 + BE2 | 18 | High |
| 10 | EP-007 | AI1 | 16 | High |
| 11 | EP-008 | AI2 | 18 | High |
| 12 | EP-009 | FE1 | 19 | High |
| 13 | EP-010 | FE1 | 13 | High |
| 14 | EP-013 | BE2 | 11 | Medium |
| 15 | EP-012 | FE1 + BE2 | 13 | Medium |
| **Total** | | | **261 pts** | |

---

## 5. Effort Estimation

### 5.1 Estimation Basis

**Conversion factor:** 1 story point = 3 hours (senior developer)
- Accounts for: coding (60%), code review (15%), testing (15%), integration (10%)
- Based on: Sprint capacity of 6 devs × 10 days × 6 effective hours/day = 360 person-hours

| Metric | Value |
|--------|-------|
| Total story points | 261 |
| Story points × 3 hours | 783 hours |
| Available capacity | 6 devs × 10 days × 6 hrs | 360 hours |
| Parallel efficiency factor | 2.2× (6 parallel workstreams) | |
| **Effective capacity** | 360 × 2.2 = **792 hours** | |
| **Buffer utilisation** | 783 / 792 = **99%** ← at capacity | |

> ⚠️ **Capacity Note:** At 99% utilisation, this plan has minimal slack. Should Have stories (FR-022 multilingual, FR-040 ML prediction, FR-044 housekeeping notification) are deferred to buffer overflow if any Must Have story runs long. Daily standups must surface blockers immediately.

### 5.2 Effort by Team Member

| Engineer | Sprint 1 Points | Sprint 2 Points | Total Points | Total Hours |
|----------|----------------|----------------|-------------|-------------|
| BE1 (Backend Lead) | EP-001(16) + EP-002(12) + EP-011(21)×50% = 38 | EP-011(21)×50% + EP-003(23)×20% = 15 | **53** | 159 hrs |
| BE2 (Backend) | EP-DATA(18) + EP-013(11)×50% = 24 | EP-013(11)×50% + EP-012(13)×50% = 12 | **36** | 108 hrs |
| AI1 (Agent Lead) | EP-003(23)×50% = 12 | EP-003(23)×50% + EP-004(24) + EP-007(16) = 52 | **64** | 192 hrs |
| AI2 (Agent) | EP-005(21)×20% = 4 | EP-005(21)×80% + EP-006(18) + EP-008(18) = 53 | **57** | 171 hrs |
| FE1 (Frontend) | EP-011 Angular(5) = 5 | EP-009(19) + EP-010(13) + EP-012(13)×50% = 39 | **44** | 132 hrs |
| DO1 (DevOps) | EP-TECH(18) + EP-011(5) = 23 | CI/CD + monitoring + review = 7 | **30** | 90 hrs |
| **Total** | | | **284 pts allocated** | **852 hrs** |

> Note: 284 allocated > 261 planned — reflects cross-epic support, integration work, and review overhead (~9% overhead is realistic).

### 5.3 Velocity Projection

| Metric | Sprint 1 | Sprint 2 | Total |
|--------|----------|----------|-------|
| Target story points | 100 | 161 | 261 |
| Stories to complete | 25 | 36 | 61 |
| Critical path items | EP-TECH, EP-DATA, EP-001, EP-002, EP-011 | All remaining | — |
| Buffer (Should Have stories deferred) | 15 pts available | 20 pts available | 35 pts |

---

## 6. Sprint Plan

### 6.1 Sprint 1 — Days 1–7: Foundation Layer

**Sprint Goal:** Provision all GCP infrastructure, establish HIPAA-compliant data foundation, build HL7/FHIR integrations, and secure the authentication layer — so that Sprint 2 agents have a working platform to run on.

**Sprint 1 Backlog (100 points)**

| Day | BE1 | BE2 | AI1 | AI2 | FE1 | DO1 |
|-----|-----|-----|-----|-----|-----|-----|
| **Day 1** | EP-002 US-001 (FHIR client) | EP-DATA US-001 (Alembic migrations) | EP-003 US-001 setup | EP-005 US-001 setup | EP-011 US-001 (OIDC flow) | EP-TECH US-001 (Terraform) |
| **Day 2** | EP-002 US-002 (retry/circuit breaker) | EP-DATA US-002 (PHI encryption) | EP-003 framework | EP-005 framework | EP-011 Angular auth | EP-TECH US-001 cont. |
| **Day 3** | EP-001 US-001 (MLLP listener) | EP-DATA US-003 (audit log) | Agent base class | Agent base class | EP-011 US-003 (RBAC) | EP-TECH US-002 (CI/CD) |
| **Day 4** | EP-001 US-002 (HL7 parser) | EP-DATA US-004 (matviews) | EP-003 US-001 cont. | EP-005 framework | EP-011 US-002 (audit log) | EP-TECH US-003 (monitoring) |
| **Day 5** | EP-001 US-003 (archival) + US-004 (Pub/Sub) | EP-DATA US-005 (pg_cron) | EP-003 US-003 (SignalR) | Integration tests | EP-011 US-005 (security headers) | EP-TECH US-004 (secrets) |
| **Day 6** | EP-001 US-005 (cancellations) + EP-002 US-003/04 | EP-011 US-004 (token blocklist) | EP-003 US-002 (SLA) | EP-005 US-002 (drug interactions) | EP-009 US-001 (Angular scaffold) | Integration + security review |
| **Day 7** | **Sprint 1 Review + Retrospective** | Integration testing | Integration testing | Integration testing | Integration testing | Deploy staging |

**Sprint 1 Exit Criteria:**
- [ ] `terraform apply` provisions all GCP resources from scratch
- [ ] `alembic upgrade head` succeeds; PHI columns encrypted in DB
- [ ] MLLP listener accepts and ACKs test ADT^A01 within 200ms
- [ ] FHIR client authenticates and fetches Patient resource from HAPI FHIR sandbox
- [ ] Staff login via SSO with MFA: JWT issued; in-memory storage confirmed
- [ ] RBAC: nurse gets 403 on pharmacist endpoint
- [ ] All Sprint 1 Must Have user stories with status = COMPLETE
- [ ] Zero CRITICAL severity findings from `bandit` SAST scan

### 6.2 Sprint 2 — Days 8–14: Feature Layer

**Sprint Goal:** Implement all 6 AI agents, care team dashboard, patient portal, and notification infrastructure — delivering a complete end-to-end care transition workflow.

**Sprint 2 Backlog (161 points)**

| Day | BE1 | BE2 | AI1 | AI2 | FE1 | DO1 |
|-----|-----|-----|-----|-----|-----|-----|
| **Day 8** | EP-003 US-004 (checklists) | EP-013 US-001 (notification dispatch) | EP-004 US-001 (discharge summary) | EP-005 US-001 (med comparison) | EP-009 US-002 (ADT feed + risk list) | End-to-end integration testing |
| **Day 9** | API review + EP-003 US-005 (DLQ) | EP-013 US-002 (OTP delivery) | EP-004 US-002 (patient instructions) | EP-005 US-002 (drug interactions) | EP-009 US-003 (approval queue) | Performance testing + load test |
| **Day 10** | API endpoints for agent results | EP-013 US-003 (delivery tracking) | EP-004 US-003 (multilingual) + EP-007 US-001 (risk scoring) | EP-005 US-003 (duplicates) + EP-006 US-001 (bed board) | EP-010 US-001 (OTP auth portal) | Cloud Monitoring alerts tuning |
| **Day 11** | Integration: agents → API | EP-012 US-001 (KPI dashboard backend) | EP-004 US-004 (review UI API) + EP-007 US-002 (high-risk pathway) | EP-006 US-002 (ML discharge prediction) + EP-008 US-001 (chatbot) | EP-009 US-004 (med queue) + EP-010 US-002 (instructions display) | Security review: HIPAA audit |
| **Day 12** | EP-004 US-005 (completeness) + agent APIs | EP-012 US-002 (CSV/PDF export) | EP-007 US-003/04 + EP-003 final | EP-006 US-003 (ED alert) + EP-008 US-002 (urgency detection) | EP-010 US-003/04 (PDF + offline) + EP-012 US-001 frontend | Final Terraform + deployment scripts |
| **Day 13** | End-to-end integration: full discharge flow | EP-012 US-003 (BigQuery) | EP-008 US-003/04 | EP-005 US-004/05 + EP-006 US-004 | EP-009 US-005 (agent monitor) | UAT environment setup |
| **Day 14** | **Sprint 2 Review + Demo + Go/No-Go** | UAT support | UAT support | UAT support | UAT support | Production deploy (if Go) |

**Sprint 2 Exit Criteria:**
- [ ] Full discharge workflow: A03 event → discharge summary generated → physician approves → patient portal active within 5 minutes
- [ ] Medication reconciliation: HIGH severity drug interaction → pharmacist alert within 60 seconds
- [ ] Bed board updates within 60 seconds of A03 event
- [ ] Risk score calculated within 60 seconds of A03; HIGH risk pathway activated
- [ ] Patient chatbot responds within 3 seconds; urgency detection fires for "chest pain"
- [ ] Angular dashboard loads in <2 seconds (Lighthouse CI)
- [ ] WCAG 2.1 AA: axe-core zero violations on all Must Have screens
- [ ] 500 concurrent user load test: p95 API <500ms

---

## 7. Milestone Schedule

### 7.1 Project Milestones

```
2026-07-13 (Day 0)   ◆ PROJECT KICKOFF
                       ├── Project plan signed off
                       ├── GCP project provisioned (prerequisite)
                       └── FHIR sandbox access confirmed

2026-07-14 (Day 1)   ◆ SPRINT 1 BEGINS
                       └── Parallel workstreams start: Terraform + Schema + HL7 + FHIR + Auth

2026-07-16 (Day 3)   ◆ M1: INFRASTRUCTURE READY
                       ├── Terraform apply: all GCP resources provisioned
                       ├── Cloud SQL schema deployed (alembic head)
                       └── CI/CD pipeline operational (first green build)

2026-07-18 (Day 5)   ◆ M2: INTEGRATION LAYER READY
                       ├── HL7 MLLP listener: ACK within 200ms ✓
                       ├── FHIR client: Patient fetch from sandbox ✓
                       └── PHI encryption: ciphertext in DB confirmed ✓

2026-07-20 (Day 7)   ◆ M3: SPRINT 1 COMPLETE (Foundation)
                       ├── Sprint 1 review & retrospective
                       ├── All Sprint 1 Must Have stories COMPLETE
                       └── Security baseline: OIDC + RBAC + audit logging ✓

2026-07-21 (Day 8)   ◆ SPRINT 2 BEGINS
                       └── Agent development + frontend parallel tracks

2026-07-23 (Day 10)  ◆ M4: AGENT CORE FUNCTIONAL
                       ├── Documentation Agent: discharge summary generated ✓
                       ├── Medication Reconciliation: drug interaction alert ✓
                       └── Bed board: real-time ADT updates ✓

2026-07-25 (Day 12)  ◆ M5: PATIENT-FACING FEATURES READY
                       ├── Patient portal: OTP auth + instructions display ✓
                       ├── Chatbot: urgency detection + escalation ✓
                       └── Angular dashboard: full role-based views ✓

2026-07-26 (Day 13)  ◆ M6: END-TO-END INTEGRATION
                       ├── Full discharge workflow tested end-to-end ✓
                       ├── Load test: 500 concurrent users, p95 <500ms ✓
                       └── HIPAA audit: PHI absent from logs ✓

2026-07-27 (Day 14)  ◆ M7: MVP DELIVERY — Go/No-Go
                       ├── Sprint 2 review & demo to stakeholders
                       ├── UAT sign-off by Product Owner
                       ├── Go/No-Go decision by Hospital Administration
                       └── Production deployment (if Go)
```

### 7.2 Critical Path

```
EP-TECH (Cloud SQL + Pub/Sub) ──► EP-DATA (schema) ──► EP-001 (HL7) ──► EP-003 (Coordinator)
                                                                              │
                                                          ┌───────────────────┤
                                                          │                   │
                                                     EP-004 (docs)      EP-005 (meds)
                                                          │                   │
                                                     EP-007 (risk)      EP-006 (beds)
                                                          │
                                                     EP-008 (chatbot)
                                                          │
                                                     EP-010 (portal)

EP-011 (security) ──► EP-009 (dashboard) ──────────────────────────────────► DEMO
```

**Critical path duration:** 14 days (zero float — any slip blocks delivery)

---

## 8. Cost Baseline

### 8.1 Labour Costs

| Role | Count | Days | Hours/Day | Hourly Rate | Total |
|------|-------|------|-----------|-------------|-------|
| Senior Full-Stack (Backend Lead) | 1 | 10 | 8 | $180 | $14,400 |
| Backend Engineer | 1 | 10 | 8 | $150 | $12,000 |
| AI/ML Engineer (Lead) | 1 | 10 | 8 | $175 | $14,000 |
| AI/ML Engineer | 1 | 10 | 8 | $160 | $12,800 |
| Senior Frontend Engineer | 1 | 10 | 8 | $165 | $13,200 |
| DevOps / Platform Engineer | 1 | 10 | 8 | $165 | $13,200 |
| **Labour Total** | **6** | **10** | | | **$79,600** |

### 8.2 GCP Infrastructure Costs (MVP Month 1)

| Service | Configuration | Monthly Cost |
|---------|--------------|--------------|
| Cloud Run (10 services, min-instances=1) | 10 × 1 vCPU × 1GB, ~20% utilisation | $280 |
| Cloud SQL PostgreSQL HA | 4 vCPU, 16GB, HA + replica, 100GB storage | $800 |
| Cloud Memorystore Redis | 2GB standard tier | $65 |
| GCP Pub/Sub | ~1.5K events/day × 30 days = 45K messages | $10 |
| Cloud Storage | HL7 archive + audit + ML models (~50GB) | $12 |
| Cloud Armor + Load Balancer | 10 rules, ~50K requests/day | $35 |
| Vertex AI (Gemini 1.5 Pro) | ~500 discharge summaries/month × $0.50/summary | $250 |
| Vertex AI (Gemini Flash) | ~5,000 chatbot queries/month × $0.05/query | $250 |
| Cloud CDN | Angular PWA static assets | $20 |
| Cloud Monitoring | Custom metrics + alerting | $15 |
| Secret Manager | ~20 secrets, 1K accesses/day | $5 |
| Twilio (SMS) | ~2,000 SMS/month × $0.0079 | $16 |
| SendGrid (Email) | ~1,000 emails/month | $10 |
| **Infrastructure Total** | | **~$1,768/month** |

> **Development phase (14 days):** ~$600 (dev/staging environments at ~50% production scale)

### 8.3 Total Project Cost Summary

| Category | Amount |
|----------|--------|
| Labour (10 working days × 6 devs) | $79,600 |
| GCP Development/Staging (14 days) | $600 |
| GCP Production (Month 1) | $1,768 |
| Tooling (Postman, BrowserStack, etc.) | $200 |
| Contingency (10%) | $8,217 |
| **Total Project Budget** | **$90,385** |

### 8.4 ROI Projection (12-Month)

| Benefit | Calculation | Annual Value |
|---------|-------------|-------------|
| Reduced discharge documentation (1.5 hrs saved × 500 discharges/month × $75/hr nurse) | 500 × 1.5 × $75 × 12 | $675,000 |
| Reduced 30-day readmissions (25% reduction × 100 readmissions/month × $15,000/readmission) | 25 × $15,000 × 12 | $4,500,000 |
| Reduced ED boarding (1 hr saved × 200 boarding events/month × $500/hr ED capacity) | 200 × 1 × $500 × 12 | $1,200,000 |
| **Total Annual Benefit (conservative)** | | **$6,375,000** |
| **Project ROI** | ($6.375M - $90K) / $90K | **~70×** |

---

## 9. Risk Register

### 9.1 Risk Assessment Matrix

| ID | Risk | Probability | Impact | Score | Mitigation | Contingency | Owner |
|----|------|-------------|--------|-------|------------|-------------|-------|
| R-001 | EHR system does not provide MLLP ADT feed (A-01 assumption) | Medium (30%) | Critical | HIGH | Confirm MLLP connectivity in Day 1; test with HL7 MLLP simulator | Implement FHIR polling fallback for Patient data; delay HL7-dependent epics | BE1 |
| R-002 | FHIR R4 endpoint unavailable or not R4-compliant (A-02) | Medium (25%) | High | HIGH | Request FHIR test environment access in Day 1; use HAPI FHIR sandbox as fallback | FHIR client degrades gracefully (partial encounter from HL7 PID only) | BE1 |
| R-003 | Vertex AI Gemini latency >25 seconds at scale | Low (20%) | High | MEDIUM | Test Gemini latency with production-scale prompts on Day 8; template fallback at 28s already built | Switch to Gemini Flash for summaries (lower quality but faster) if needed | AI1 |
| R-004 | ML model accuracy insufficient (AUC <0.80) due to limited training data | Medium (35%) | Medium | MEDIUM | Request historical encounter data in Day 1; fall back to heuristic risk scoring if data insufficient | Rule-based risk scoring (LOS >5 days, ≥2 comorbidities, prior readmission = HIGH risk) | AI1, AI2 |
| R-005 | Angular bundle size exceeds 500KB (NFR-001 at risk) | Medium (30%) | Medium | MEDIUM | Lighthouse CI budget in CI from Day 8; aggressive lazy loading from scaffold day | Defer analytics module to reduce initial bundle; use CDN pre-loading for critical chunks | FE1 |
| R-006 | 14-day timeline at capacity (261 pts / 261 pt capacity) — zero float | High (60%) | High | HIGH | Daily standup blocker escalation; Should Have stories deferred immediately on any Must Have slip | Defer EP-012 (analytics) and Should Have stories; focus on Must Have delivery | PM |
| R-007 | PHI leakage in LLM prompts | Low (10%) | Critical | HIGH | Log sanitiser middleware + Vertex AI prompt logging disabled (Day 1 config); quarterly audit | Immediately disable affected agent; incident response plan activated | BE1, AI1 |
| R-008 | GCP Vertex AI API quota exceeded at peak discharge time | Low (20%) | High | MEDIUM | Token usage monitoring + budget alert (Day 1 config); LLaMA 3 fallback prepared | Template-based discharge summary fallback (already built in EP-004); notify clinical staff | AI1, DO1 |
| R-009 | Hospital SSO / Identity Provider not accessible from GCP network | Medium (25%) | High | HIGH | Confirm SSO connectivity and OIDC discovery URL in Day 1; test JWKS fetch from GCP | Implement local dev auth mode (JWT signing key only) for demo; SSO for production | BE1 |
| R-010 | Scikit-learn model drift: accuracy degrades post-deployment | Low (15%) | Medium | LOW | Monthly model evaluation scheduled; AUC monitoring in BigQuery | Retrain with updated encounter data; fallback to rule-based scoring | AI1 |

### 9.2 Risk Heat Map

```
        IMPACT
        Critical    High      Medium     Low
       ┌──────────┬─────────┬──────────┬─────┐
High   │          │  R-006  │          │     │
       ├──────────┼─────────┼──────────┼─────┤
Medium │  R-007   │ R-001   │  R-003   │     │
       │          │ R-002   │  R-004   │     │
       │          │ R-009   │  R-005   │     │
       │          │         │  R-008   │     │
       ├──────────┼─────────┼──────────┼─────┤
Low    │          │         │          │ R-010│
       └──────────┴─────────┴──────────┴─────┘
PROBABILITY
```

### 9.3 Top 3 Risk Mitigations (Actions on Day 1)

1. **R-001 + R-002 (EHR Access):** BE1 to verify MLLP connectivity and FHIR endpoint accessibility before end of Day 1. If not accessible by Day 2, activate fallback plan and notify PM immediately.
2. **R-006 (Timeline):** Product Owner to sign off on Should Have deferral list before Sprint 2 begins. Any Must Have story not completed by Day 5 triggers automatic removal of one Should Have from Sprint 2.
3. **R-009 (SSO Access):** BE1 to validate OIDC discovery URL and JWKS fetch from GCP network before starting EP-011. Prepare local JWT-only auth mode as Day 1 fallback.

---

## 10. Dependency Matrix

### 10.1 Critical Dependencies

| Dependent Epic | Depends On | Dependency Type | Slip Impact |
|----------------|-----------|-----------------|-------------|
| EP-001 (HL7 Ingestion) | EP-TECH (Pub/Sub, Cloud Storage) | Infrastructure | HL7 cannot publish events |
| EP-001 (HL7 Ingestion) | EP-DATA (adt_event schema) | Schema | ADT events cannot be persisted |
| EP-003 (Coordinator) | EP-001 (Pub/Sub events) | Data flow | Agents never triggered |
| EP-004 (Documentation) | EP-002 (FHIR client) | Service | Discharge summaries have no patient data |
| EP-004 (Documentation) | EP-003 (AgentTask framework) | Framework | No task tracking or SignalR push |
| EP-005 (Med Recon) | EP-002 (FHIR med lists) | Service | No medication data to reconcile |
| EP-007 (Risk Scoring) | EP-TECH (ML Inference Cloud Run) | Infrastructure | No risk score ML inference |
| EP-008 (Chatbot) | EP-004 (Approved documents) | Data | No discharge context for chatbot |
| EP-009 (Dashboard) | EP-011 (Auth/JWT) | Security | Dashboard inaccessible without auth |
| EP-010 (Portal) | EP-013 (OTP SMS) | Integration | Patients cannot authenticate |
| EP-010 (Portal) | EP-004 (Patient instructions) | Data | Nothing to display in portal |

### 10.2 External Dependencies

| Dependency | Owner | Required By | Risk |
|------------|-------|-------------|------|
| GCP project + billing activation | Hospital IT | Day 0 | Blocks everything |
| Hospital SSO OIDC discovery URL | Hospital IT | Day 1 | Blocks EP-011 |
| FHIR R4 endpoint access credentials | EHR Vendor | Day 1 | Blocks EP-002 |
| HL7 MLLP connectivity (port 2575) | Hospital IT | Day 1 | Blocks EP-001 |
| Twilio account + Verify service SID | DevOps | Day 1 | Blocks EP-013 |
| SendGrid API key + template IDs | DevOps | Day 1 | Blocks EP-013 |
| Historical encounter data for ML training | Hospital IT | Day 3 | Blocks EP-006, EP-007 ML models |
| Vertex AI API quota approval | Google/Hospital | Day 1 | Blocks EP-004, EP-008 |

---

## 11. Governance & Communication Plan

### 11.1 Ceremonies

| Ceremony | Frequency | Duration | Participants | Output |
|----------|-----------|----------|-------------|--------|
| Daily Standup | Daily (Mon–Fri) 09:00 | 15 min | All 6 devs | Blocker list; today's focus |
| Sprint 1 Review | Day 7 (15:00) | 60 min | Dev team + Product Owner | Sprint 1 demo; accepted stories |
| Sprint 1 Retro | Day 7 (16:00) | 45 min | Dev team | Improvement actions for Sprint 2 |
| Mid-Sprint Check-in | Day 11 (14:00) | 30 min | Dev team + PM | Risk review; scope adjustment |
| Sprint 2 Review / Demo | Day 14 (14:00) | 90 min | All stakeholders | Full product demo; Go/No-Go |
| Go/No-Go Meeting | Day 14 (16:00) | 30 min | Hospital Admin, CMO, CNO, IT Director, PM | Production deployment decision |

### 11.2 Communication Matrix

| Audience | Information | Channel | Frequency |
|----------|-------------|---------|-----------|
| Development Team | Daily progress, blockers, technical decisions | Slack / Teams #dev-smarthandoff | Daily |
| Product Owner | Story acceptance, scope changes, risk escalations | Direct message + daily standup | Daily |
| Hospital Administration | Milestone completions, budget status, risks | Email summary | Weekly (Day 7, Day 14) |
| CMO / CNO | Clinical accuracy validation requests, UAT participation | Email + meeting | Day 12 (UAT), Day 14 (demo) |
| IT Director | Security review results, infrastructure status | Technical report | Day 7, Day 14 |
| Compliance Officer | HIPAA audit log verification | Written confirmation | Day 13 |

### 11.3 Decision Authority

| Decision Type | Authority | Escalation Path |
|---------------|-----------|-----------------|
| Technical architecture changes | Backend Lead (BE1) | → PM → Product Owner |
| Scope additions | Product Owner | → Hospital Administration |
| Scope reductions (Must Have deferral) | PM + Product Owner joint | → CMO/CNO notification |
| Security exceptions | BE1 + DO1 joint | → IT Director → Compliance Officer |
| Go/No-Go for production | Hospital Administration | Final authority |
| Budget overrun >10% | PM + Product Owner | → Hospital Administration |

### 11.4 Change Control

1. **Change request raised** by any team member in #dev-smarthandoff channel with: description, impact on scope/timeline/cost, recommendation
2. **PM assesses** impact within 2 hours; classifies as: Minor (no scope change) / Significant (scope/timeline impact) / Major (cost impact)
3. **Minor:** PM approves; logged in change log
4. **Significant:** PM + Product Owner approve; sprint backlog updated
5. **Major:** Hospital Administration approval required; documented in project plan amendment

---

## 12. Definition of Done & Quality Gates

### 12.1 Story-Level Definition of Done

A user story is COMPLETE only when ALL of the following are met:

- [ ] **Code complete:** All acceptance criteria implemented; no TODO/FIXME comments in PR
- [ ] **Unit tests:** ≥80% coverage for new code; all tests passing in CI
- [ ] **Integration test:** Story-specific integration test written and passing
- [ ] **Code review:** Minimum 1 peer review approved (security-related: BE1 required)
- [ ] **No OWASP violations:** bandit + safety scan passes with zero HIGH severity findings
- [ ] **No PHI in logs:** Cloud Logging search confirms no PHI field names after testing
- [ ] **Acceptance criteria verified:** Product Owner or designated reviewer confirms all ACs pass
- [ ] **Documentation:** API changes reflected in OpenAPI spec; README updated if needed

### 12.2 Sprint-Level Quality Gates

**Sprint 1 Quality Gate (must pass before Sprint 2 starts):**
- [ ] All Sprint 1 Must Have stories: COMPLETE
- [ ] `terraform apply` clean from scratch in CI
- [ ] `alembic upgrade head` zero errors in staging DB
- [ ] MLLP listener: ACK within 200ms for 100 test messages
- [ ] FHIR client: 7 resource types validated against R4 schema
- [ ] OIDC login + RBAC: 35 role × endpoint tests passing
- [ ] PHI encrypted in DB: direct SQL confirms ciphertext
- [ ] PHI absent from Cloud Logging: 20 API call audit confirms

**Sprint 2 Quality Gate (must pass for Go/No-Go):**
- [ ] Full discharge workflow end-to-end: A03 → approved discharge summary → patient portal: <5 minutes
- [ ] Drug interaction detection: ≥99% on 200 reference test cases
- [ ] Readmission risk score: AUC ≥0.80 on holdout dataset
- [ ] Angular Lighthouse LCP: <2 seconds
- [ ] axe-core: zero WCAG 2.1 AA violations on all 8 Must Have screens
- [ ] 500 concurrent user load test: p95 API <500ms
- [ ] HIPAA audit: compliance officer sign-off on PHI protection
- [ ] Security: Cloud Armor WAF active; security headers on all endpoints

### 12.3 Production Readiness Checklist

- [ ] All 55 Must Have FRs implemented and accepted
- [ ] HIPAA compliance verified by Compliance Officer
- [ ] IT Director sign-off on security architecture
- [ ] Cloud SQL HA failover tested and <60 seconds
- [ ] Cloud SQL PITR verified (restore to 15 minutes ago)
- [ ] Runbook documented: incident response, break-glass auth, rollback procedure
- [ ] Monitoring alerts: all P1/P2/P3 alert policies active and tested
- [ ] On-call rotation established and notified

---

## 13. Assumptions & Constraints

### 13.1 Key Assumptions

| ID | Assumption | Validation Date | Fallback |
|----|------------|-----------------|---------|
| A-01 | EHR transmits HL7 v2.x ADT via MLLP on port 2575 | Day 1 | FHIR polling fallback |
| A-02 | Hospital has FHIR R4 endpoint accessible from GCP | Day 1 | CSV import fallback; partial encounters from HL7 PID |
| A-03 | Staff have basic computer literacy (web browser, email) | Day 12 (UAT) | Extended training materials |
| A-04 | Reliable internet ≥10 Mbps in hospital | Day 1 | PWA offline caching for patient portal |
| A-05 | GCP services available in required region (`us-central1`) | Day 1 | Alternative region selection |
| A-06 | Budget approved for Vertex AI API usage | Day 1 | LLaMA 3 open-source LLM fallback |
| A-07 | Historical encounter data available for ML model training (≥12 months, ≥1,000 records) | Day 3 | Rule-based risk scoring heuristics |
| A-08 | Hospital IT provides GCP project with billing by Day 0 | Day 0 | Project cannot start |
| A-09 | Twilio and SendGrid accounts provisioned and verified | Day 1 | EP-013 deferred; manual notification fallback |

### 13.2 Hard Constraints

| ID | Constraint | Impact on Plan |
|----|------------|----------------|
| C-01 | 14-calendar-day development timeline | MVP scope strictly enforced; Should Have deferred |
| C-02 | 6-developer team | All workstreams run in parallel from Day 1 |
| C-03 | No EHR write-back in Phase 1 | FHIR read-only; appointment records internal only |
| C-04 | HIPAA compliance mandatory from Day 1 | PHI encryption and audit logging in Sprint 1 (not deferred) |
| C-05 | GCP-only infrastructure | No AWS/Azure services; GCP quota must be pre-approved |
| C-06 | Must integrate with existing hospital SSO | OAuth2/OIDC adapter required; SSO must be accessible from GCP |

### 13.3 Scope Management Rules

1. **Must Have stories cannot be descoped** without CMO/CNO approval and documented patient safety impact assessment
2. **Should Have stories** are the first buffer: any Must Have overrun > 4 hours → immediately defer one Should Have of equivalent points
3. **Timeline is fixed:** No timeline extension without Hospital Administration approval and full revised cost baseline
4. **Team is fixed at 6:** No contractor additions without ≥3 days onboarding overhead factored into revised plan
5. **New features discovered during development** are logged as post-MVP items; not added to current sprint without explicit Product Owner approval and equivalent story removal

---

*End of SmartHandoff Project Plan — Version 1.0 | Generated: 2026-07-13*
