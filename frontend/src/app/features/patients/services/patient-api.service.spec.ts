import { TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import { PatientApiService } from './patient-api.service';
import { environment } from '../../../../environments/environment';
import { RiskTier } from '../../../shared/models';

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
