---
id: TASK-002
title: "Implement `MedicationApiService` and `InteractionAlertApiService`"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Service Layer
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-030, US-031]
---

# TASK-002: Implement `MedicationApiService` and `InteractionAlertApiService`

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Service Layer | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

The `MedicationReviewComponent` (TASK-001) and `AlertResolutionModalComponent` (TASK-003) both require Angular services to communicate with the backend APIs delivered by US-030 (Medication Reconciliation) and US-031 (Interaction Alert). These services are the single-source HTTP clients for their respective domains — no component makes direct `HttpClient` calls (DRY, Separation of Concerns).

Both services use `inject(HttpClient)`, return typed `Observable` responses, and handle error mapping to surface consistent error shapes to consumers.

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **Scenario 1** | API delivers three-panel reconciliation data to `MedicationReviewComponent` |
| **Scenario 2** | Alert resolution API call clears badge on submit |

---

## Implementation Steps

### 1. Create `MedicationApiService` in `features/medications/services/`

**`medication-api.service.ts`**

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { MedicationReconciliation } from '../models/medication-row.model';

/**
 * HTTP client for medication reconciliation endpoints.
 * Source: US-030 Medication Reconciliation API.
 *
 * Base path: /api/v1/patients/{patientId}/medications
 */
@Injectable({ providedIn: 'root' })
export class MedicationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/patients`;

  /**
   * Retrieves the three-panel reconciliation payload for a patient.
   * GET /api/v1/patients/{patientId}/medications/reconciliation
   */
  getReconciliation(patientId: string): Observable<MedicationReconciliation> {
    return this.http.get<MedicationReconciliation>(
      `${this.base}/${patientId}/medications/reconciliation`
    );
  }
}
```

### 2. Define Interaction Alert Models in `features/medications/models/`

**`interaction-alert.model.ts`**

```typescript
/**
 * Interaction alert as returned by GET /api/v1/alerts/{alertId}.
 * Source: US-031 Interaction Alert API.
 */
export interface InteractionAlert {
  alertId: string;
  encounterId: string;
  drug1Name: string;
  drug2Name: string;
  /** First 200 characters of RxNav interaction description */
  descriptionExcerpt: string;
  /** Full description — loaded on "Read more" expansion */
  descriptionFull: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  status: 'OPEN' | 'RESOLVED';
}

/**
 * Resolution payload sent to PATCH /api/v1/alerts/{alertId}/resolve.
 */
export interface AlertResolutionPayload {
  resolutionType: AlertResolutionType;
  /** Optional clinician note, max 500 characters */
  note?: string;
}

export type AlertResolutionType =
  | 'REVIEWED_ACCEPTABLE'
  | 'DOSE_ADJUSTED'
  | 'DRUG_CHANGED'
  | 'DISCONTINUED';
```

### 3. Create `InteractionAlertApiService` in `features/medications/services/`

**`interaction-alert-api.service.ts`**

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import {
  InteractionAlert,
  AlertResolutionPayload,
} from '../models/interaction-alert.model';

/**
 * HTTP client for interaction alert endpoints.
 * Source: US-031 Interaction Alert API.
 *
 * Base path: /api/v1/alerts
 */
@Injectable({ providedIn: 'root' })
export class InteractionAlertApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/alerts`;

  /**
   * Fetches full alert detail including drug pair and RxNav description.
   * GET /api/v1/alerts/{alertId}
   */
  getAlert(alertId: string): Observable<InteractionAlert> {
    return this.http.get<InteractionAlert>(`${this.base}/${alertId}`);
  }

  /**
   * Submits clinician resolution for a drug interaction alert.
   * PATCH /api/v1/alerts/{alertId}/resolve
   *
   * On success, the backend sets status = RESOLVED and emits a SignalR
   * `alert_resolved` event to the encounter group.
   */
  resolveAlert(
    alertId: string,
    payload: AlertResolutionPayload
  ): Observable<InteractionAlert> {
    return this.http.patch<InteractionAlert>(
      `${this.base}/${alertId}/resolve`,
      payload
    );
  }
}
```

### 4. Create `DocumentApiService` in `features/documents/services/`

> **Note:** The document API service is consumed by `DocumentQueueComponent` (TASK-004) and delivers the physician's approval queue.

**`document-api.service.ts`**

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { PendingDocument, DocumentActionPayload } from '../models/pending-document.model';

/**
 * HTTP client for document approval queue endpoints.
 * Source: US-025 Document API.
 *
 * Base path: /api/v1/documents
 */
@Injectable({ providedIn: 'root' })
export class DocumentApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/documents`;

  /**
   * Returns all PENDING_REVIEW documents assigned to the current physician.
   * GET /api/v1/documents?status=PENDING_REVIEW&assignedTo=me
   */
  getPendingReviewQueue(): Observable<PendingDocument[]> {
    const params = new HttpParams()
      .set('status', 'PENDING_REVIEW')
      .set('assignedTo', 'me');
    return this.http.get<PendingDocument[]>(this.base, { params });
  }

  /**
   * Approves or rejects a document.
   * PATCH /api/v1/documents/{documentId}/review
   */
  reviewDocument(
    documentId: string,
    payload: DocumentActionPayload
  ): Observable<PendingDocument> {
    return this.http.patch<PendingDocument>(
      `${this.base}/${documentId}/review`,
      payload
    );
  }
}
```

**`pending-document.model.ts`** (create in `features/documents/models/`):

```typescript
/**
 * Document awaiting physician approval.
 * Source: US-025 Document API response schema.
 */
export interface PendingDocument {
  documentId: string;
  encounterId: string;
  patientName: string;
  documentType: 'DISCHARGE_SUMMARY' | 'PATIENT_INSTRUCTIONS' | 'REFERRAL';
  generatedAt: string; // ISO 8601
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED';
  /** AI-generated content excerpt (first 200 chars) */
  contentExcerpt: string;
}

export interface DocumentActionPayload {
  action: 'APPROVED' | 'REJECTED';
  /** Optional rejection reason, required when action = REJECTED */
  rejectionReason?: string;
}
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| CREATE | `src/app/features/medications/models/interaction-alert.model.ts` |
| CREATE | `src/app/features/medications/services/medication-api.service.ts` |
| CREATE | `src/app/features/medications/services/interaction-alert-api.service.ts` |
| CREATE | `src/app/features/documents/models/pending-document.model.ts` |
| CREATE | `src/app/features/documents/services/document-api.service.ts` |

---

## Validation Checklist

- [ ] `MedicationApiService.getReconciliation()` returns typed `Observable<MedicationReconciliation>`
- [ ] `InteractionAlertApiService.getAlert()` returns typed `Observable<InteractionAlert>`
- [ ] `InteractionAlertApiService.resolveAlert()` sends PATCH with `AlertResolutionPayload`
- [ ] `DocumentApiService.getPendingReviewQueue()` sends `status=PENDING_REVIEW&assignedTo=me`
- [ ] `DocumentApiService.reviewDocument()` sends PATCH with action payload
- [ ] No raw `any` types used in service signatures
- [ ] All services use `inject(HttpClient)` — not constructor injection
- [ ] Services are `providedIn: 'root'` — no module registration required

---

## Dependencies

| Dependency | Notes |
|---|---|
| US-030 | Medication Reconciliation API — endpoint schema must match `MedicationReconciliation` model |
| US-031 | Interaction Alert API — endpoint schema must match `InteractionAlert` model |
| US-025 | Document API — endpoint schema must match `PendingDocument` model |
| US-047 | `environment.apiBaseUrl` defined in Angular scaffold |
