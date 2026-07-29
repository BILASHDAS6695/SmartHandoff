import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { HttpClient, HttpRequest } from '@angular/common/http';
import { jwtInterceptor } from './jwt.interceptor';
import { AuthService } from './auth.service';
import { environment } from '../../../environments/environment';

/**
 * Unit tests for jwtInterceptor.
 *
 * Coverage target: ≥80% branch coverage.
 *
 * Design refs:
 *   US-047 AC Scenario 4 — JWT scoping to API origin only
 *   US-056 TASK-005 — JWT interceptor implementation
 */
describe('jwtInterceptor', () => {
  let httpClient: HttpClient;
  let httpMock: HttpTestingController;
  let authService: AuthService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [AuthService],
    });

    httpClient = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should attach Authorization header to API requests when token exists', () => {
    const token = 'test-jwt-token';
    jest.spyOn(authService, 'getToken').mockReturnValue(token);

    httpClient.get('/api/patients').subscribe();

    const req = httpMock.expectOne('/api/patients');
    expect(req.request.headers.has('Authorization')).toBe(true);
    expect(req.request.headers.get('Authorization')).toBe(`Bearer ${token}`);
  });

  it('should attach Authorization header to requests targeting apiBaseUrl', () => {
    const token = 'test-jwt-token';
    jest.spyOn(authService, 'getToken').mockReturnValue(token);

    // Use environment apiBaseUrl if configured
    if (environment.apiBaseUrl) {
      httpClient.get(`${environment.apiBaseUrl}/patients`).subscribe();
      const req = httpMock.expectOne(`${environment.apiBaseUrl}/patients`);
      expect(req.request.headers.get('Authorization')).toBe(`Bearer ${token}`);
    }
  });

  it('should not attach Authorization header when token is missing', () => {
    jest.spyOn(authService, 'getToken').mockReturnValue(null);

    httpClient.get('/api/patients').subscribe();

    const req = httpMock.expectOne('/api/patients');
    expect(req.request.headers.has('Authorization')).toBe(false);
  });

  it('should not attach Authorization header to external URLs', () => {
    const token = 'test-jwt-token';
    jest.spyOn(authService, 'getToken').mockReturnValue(token);

    httpClient.get('https://external-api.com/data').subscribe();

    const req = httpMock.expectOne('https://external-api.com/data');
    expect(req.request.headers.has('Authorization')).toBe(false);
  });

  it('should not attach Authorization header to CDN requests', () => {
    const token = 'test-jwt-token';
    jest.spyOn(authService, 'getToken').mockReturnValue(token);

    httpClient.get('https://cdn.example.com/font.woff2').subscribe();

    const req = httpMock.expectOne('https://cdn.example.com/font.woff2');
    expect(req.request.headers.has('Authorization')).toBe(false);
  });
});
