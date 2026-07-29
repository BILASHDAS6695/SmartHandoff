import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { authGuard } from './auth.guard';
import { AuthService } from './auth.service';

/**
 * Unit tests for authGuard.
 *
 * Coverage target: ≥80% branch coverage.
 *
 * Design refs:
 *   US-047 TASK-003 — auth guard route protection
 *   US-056 TASK-006 — auth guard implementation
 */
describe('authGuard', () => {
  let router: Router;
  let authService: AuthService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [RouterTestingModule, HttpClientTestingModule],
      providers: [AuthService],
    });

    router = TestBed.inject(Router);
    authService = TestBed.inject(AuthService);
  });

  it('should allow navigation when user is authenticated', () => {
    jest.spyOn(authService, 'isAuthenticated').mockReturnValue(true);

    const result = TestBed.runInInjectionContext(() => authGuard);

    expect(result).toBe(true);
  });

  it('should redirect to /login when user is not authenticated', () => {
    jest.spyOn(authService, 'isAuthenticated').mockReturnValue(false);
    const createUrlTreeSpy = jest.spyOn(router, 'createUrlTree');

    TestBed.runInInjectionContext(() => authGuard);

    expect(createUrlTreeSpy).toHaveBeenCalledWith(['/login'], expect.any(Object));
  });

  it('should include returnUrl query parameter', () => {
    jest.spyOn(authService, 'isAuthenticated').mockReturnValue(false);
    const createUrlTreeSpy = jest.spyOn(router, 'createUrlTree');

    TestBed.runInInjectionContext(() => authGuard);

    expect(createUrlTreeSpy).toHaveBeenCalledWith(
      ['/login'],
      expect.objectContaining({
        queryParams: expect.objectContaining({
          returnUrl: expect.any(String),
        }),
      }),
    );
  });
});
