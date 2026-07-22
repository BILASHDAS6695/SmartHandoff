import { HttpInterceptorFn, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';
import { environment } from '../../../environments/environment';

/**
 * JwtInterceptor — attaches Authorization: Bearer header to API requests.
 *
 * Only attaches the token to requests targeting the configured API base URL
 * or relative /api paths. This prevents the JWT from being sent to third-party
 * URLs (e.g. RxNav API, FHIR external endpoints).
 */
export const jwtInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  const authService = inject(AuthService);
  const token = authService.getToken();

  const isApiRequest =
    req.url.startsWith('/api') ||
    (environment.apiBaseUrl !== '' && req.url.startsWith(environment.apiBaseUrl));

  if (token && isApiRequest) {
    const authReq = req.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    });
    return next(authReq);
  }

  return next(req);
};
