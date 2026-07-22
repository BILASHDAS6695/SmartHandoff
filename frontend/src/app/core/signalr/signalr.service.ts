/**
 * SignalR service stub.
 *
 * TODO(US-056): When the SignalR story is implemented, use accessTokenFactory:
 *
 *   this.connection = new HubConnectionBuilder()
 *     .withUrl(`${environment.apiBaseUrl}/hubs/dashboard`, {
 *       accessTokenFactory: () => this.authService.getToken() ?? '',
 *     })
 *     .withAutomaticReconnect()
 *     .build();
 *
 * Per US-056 Technical Notes:
 *   HubConnectionBuilder.withUrl(url, { accessTokenFactory: () => authService.getToken() })
 */
import { Injectable } from '@angular/core';
import { AuthService } from '../auth/auth.service';

@Injectable({ providedIn: 'root' })
export class SignalRService {
  constructor(private readonly authService: AuthService) {}
}
