---
id: TASK-002
title: "Implement `PatientApiService` with Unit-Scoped RBAC, Search, and Pagination"
user_story: US-049
epic: EP-009
sprint: 2
layer: Frontend — Service / API Client
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-071, FR-074]
---

# TASK-002: Implement `PatientApiService` with Unit-Scoped RBAC, Search, and Pagination

> **Story:** US-049 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Service / API Client | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

The patient list requires an Angular service that calls `GET /api/v1/patients` with unit-scoped filtering derived from the nurse's JWT claims. The server enforces the `unit` filter (FR-074 — server-side RBAC), but Angular must pass the correct `unit` query parameter sourced from the decoded JWT claim `units[]`. The service also handles paginated responses (25 per page), search term forwarding, and exposes typed observables consumed by `PatientListComponent`.

This service is the single integration point for all patient list data — it must NOT be duplicated in individual components.

---

## Acceptance Criteria Addressed

| US-049 AC | Requirement |
|---|---|
| **Scenario 1** | `GET /api/v1/patients?unit={unit}` called with unit from JWT; server enforces filter |
| **Scenario 4** | Search term forwarded as `?search={term}&unit={unit}`; 300ms debounce handled in component (TASK-003) |

---

## Implementation Steps

### 1. Define API Response Models in `patients/models/patient.model.ts`

```typescript
import { RiskTier } from '../../../shared/models/risk-tier.enum';

/** Encounter-level patient record as returned by GET /api/v1/patients */
export interface PatientSummary {
  encounter_id: string;
  patient_id: string;
  /** Masked MRN — last 4 digits only, per HIPAA minimum-necessary */
  mrn_masked: string;
  first_name: string;
  last_name: string;
  date_of_birth: string; // ISO 8601
  current_unit: string;
  room_number: string;
  risk_tier: RiskTier;
  risk_score: number | null;
  admission_date: string; // ISO 8601
}

/** Paginated list response envelope */
export interface PatientListResponse {
  items: PatientSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** Query parameters for GET /api/v1/patients */
export interface PatientListQuery {
  unit: string;
  search?: string;
  page?: number;
  page_size?: number;
}
```

### 2. Create `PatientApiService` in `features/patients/services/patient-api.service.ts`

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { PatientListQuery, PatientListResponse } from '../models/patient.model';

/**
 * HTTP client for the patient list API endpoint.
 *
 * RBAC note: the `unit` parameter is always set by the caller (PatientListComponent)
 * reading from the decoded JWT claim. The server re-enforces this filter independently
 * (FR-074). This service does NOT perform client-side filtering.
 */
@Injectable({ providedIn: 'root' })
export class PatientApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/patients`;

  /**
   * Fetches paginated patient list for the specified unit.
   * @param query - Unit, optional search term, page, and page_size
   */
  getPatients(query: PatientListQuery): Observable<PatientListResponse> {
    let params = new HttpParams()
      .set('unit', query.unit)
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.page_size ?? 25));

    if (query.search?.trim()) {
      params = params.set('search', query.search.trim());
    }

    return this.http.get<PatientListResponse>(this.baseUrl, { params });
  }
}
```

### 3. Unit Tests — `patient-api.service.spec.ts`

```typescript
import { TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import { PatientApiService } from './patient-api.service';
import { environment } from '../../../../environments/environment';
import { RiskTier } from '../../../shared/models/risk-tier.enum';

describe('PatientApiService', () => {
  let service: PatientApiService;
  let httpMock: HttpTestingController;
  const baseUrl = `${environment.apiBaseUrl}/api/v1/patients`;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
    });
    service = TestBed.inject(PatientApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should call GET /api/v1/patients with unit param', () => {
    service.getPatients({ unit: '3A' }).subscribe();
    const req = httpMock.expectOne(r => r.url === baseUrl);
    expect(req.request.params.get('unit')).toBe('3A');
    expect(req.request.params.get('page')).toBe('1');
    req.flush({ items: [], total: 0, page: 1, page_size: 25 });
  });

  it('should include search param when provided', () => {
    service.getPatients({ unit: '3A', search: 'Smith' }).subscribe();
    const req = httpMock.expectOne(r => r.url === baseUrl);
    expect(req.request.params.get('search')).toBe('Smith');
    req.flush({ items: [], total: 0, page: 1, page_size: 25 });
  });

  it('should omit search param when empty string', () => {
    service.getPatients({ unit: '3A', search: '  ' }).subscribe();
    const req = httpMock.expectOne(r => r.url === baseUrl);
    expect(req.request.params.has('search')).toBeFalse();
    req.flush({ items: [], total: 0, page: 1, page_size: 25 });
  });

  it('should use default page_size of 25', () => {
    service.getPatients({ unit: '3A' }).subscribe();
    const req = httpMock.expectOne(r => r.url === baseUrl);
    expect(req.request.params.get('page_size')).toBe('25');
    req.flush({ items: [], total: 0, page: 1, page_size: 25 });
  });
});
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `frontend/src/app/features/patients/models/patient.model.ts` |
| **Create** | `frontend/src/app/features/patients/services/patient-api.service.ts` |
| **Create** | `frontend/src/app/features/patients/services/patient-api.service.spec.ts` |

---

## Definition of Done

- [ ] `PatientSummary`, `PatientListResponse`, and `PatientListQuery` interfaces defined with `RiskTier` reference
- [ ] `PatientApiService.getPatients()` always passes `unit` param; never filters client-side
- [ ] Empty/whitespace `search` string omitted from query params
- [ ] All 4 unit tests pass with `HttpClientTestingModule`
- [ ] `providedIn: 'root'` — no lazy-load duplication concern

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `RiskTier` enum must exist at `shared/models/risk-tier.enum.ts` |
| US-047 | Story | Angular scaffold with `HttpClientModule` and `environment` configs |
| US-039 | Story | Risk tier values produced by risk scoring API — `risk_tier` field on encounter response |
