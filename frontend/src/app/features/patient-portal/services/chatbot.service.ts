/**
 * ChatbotService — sends patient messages to POST /api/v1/chat.
 *
 * Authentication: patient JWT injected automatically by JwtInterceptor (core/auth).
 * The encounter_id is extracted from the JWT 'encounter_id' claim via AuthService.
 *
 * Design refs:
 *   US-055 AC Scenario 1 — POST /api/v1/chat with patient JWT
 *   US-055 AC Scenario 3 — encounter_id from JWT ensures server-side scope enforcement
 *   TR-006              — chatbot response time target <3 seconds
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { AuthService } from '../../../core/auth/auth.service';
import { ChatRequest, ChatResponse } from '../models/chat.model';

@Injectable({ providedIn: 'root' })
export class ChatbotService {
  private readonly http = inject(HttpClient);
  private readonly authService = inject(AuthService);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/chat`;

  /**
   * Send a patient message to the chat API.
   * encounter_id is sourced from the JWT claim — never passed by the caller.
   */
  sendMessage(userMessage: string): Observable<ChatResponse> {
    const encounterId = this.authService.getPatientClaim<string>('encounter_id');
    if (!encounterId) {
      throw new Error('encounter_id not found in JWT claims');
    }
    const body: ChatRequest = { encounter_id: encounterId, message: userMessage };
    return this.http.post<ChatResponse>(this.baseUrl, body);
  }
}
