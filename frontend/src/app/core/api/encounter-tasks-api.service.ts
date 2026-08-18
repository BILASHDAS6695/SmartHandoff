/**
 * EncounterTasksApiService — REST API client for encounter task operations.
 *
 * US-022 Scenario 3 requirement:
 *   On SignalR reconnect, re-fetch missed task updates via GET /api/v1/encounters/{id}/tasks
 *
 * US-022 Integration:
 *   - SignalRService calls getTasksForEncounter() on reconnection
 *   - DashboardComponent uses this service for initial task load
 *
 * Design: Standalone Angular service using HttpClient with JWT interceptor.
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError, retry } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { AgentTaskResponse } from '../models/task.model';

@Injectable({ providedIn: 'root' })
export class EncounterTasksApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1`;

  /**
   * Fetches all tasks for a given encounter.
   *
   * Used by:
   *   - DashboardComponent for initial task load
   *   - SignalRService for missed task re-fetch on reconnection
   *
   * @param encounterId - UUID of the encounter
   * @returns Observable of task array
   */
  getTasksForEncounter(encounterId: string): Observable<AgentTaskResponse[]> {
    return this.http
      .get<AgentTaskResponse[]>(`${this.baseUrl}/encounters/${encounterId}/tasks`)
      .pipe(
        retry(2), // Retry up to 2 times on transient failures
        catchError(this._handleError)
      );
  }

  /**
   * Fetches tasks assigned to the current user across all encounters.
   *
   * Used by DashboardComponent when no encounter context is present.
   *
   * @param status - Optional status filter
   * @returns Observable of task array
   */
  getMyTasks(status?: string): Observable<AgentTaskResponse[]> {
    let params = new HttpParams();
    if (status) {
      params = params.set('status', status);
    }
    return this.http
      .get<AgentTaskResponse[]>(`${this.baseUrl}/tasks`, { params })
      .pipe(
        retry(2),
        catchError(this._handleError)
      );
  }

  /**
   * Fetches a specific task by ID.
   *
   * @param taskId - UUID of the task
   * @returns Observable of task detail
   */
  getTaskById(taskId: string): Observable<AgentTaskResponse> {
    return this.http
      .get<AgentTaskResponse>(`${this.baseUrl}/tasks/${taskId}`)
      .pipe(
        retry(2),
        catchError(this._handleError)
      );
  }

  /** Queue a new execution for a failed agent task. */
  retryFailedTask(taskId: string): Observable<AgentTaskResponse> {
    return this.http
      .post<AgentTaskResponse>(`${this.baseUrl}/tasks/${taskId}/retry`, {})
      .pipe(catchError(this._handleError));
  }

  /**
   * Fetches tasks filtered by status.
   *
   * @param encounterId - UUID of the encounter
   * @param status - Task status filter
   * @returns Observable of filtered task array
   */
  getTasksByStatus(
    encounterId: string,
    status: string
  ): Observable<AgentTaskResponse[]> {
    return this.http
      .get<AgentTaskResponse[]>(
        `${this.baseUrl}/encounters/${encounterId}/tasks?status=${status}`
      )
      .pipe(
        retry(2),
        catchError(this._handleError)
      );
  }

  /**
   * Fetches tasks filtered by target role.
   *
   * @param encounterId - UUID of the encounter
   * @param role - Care team role filter
   * @returns Observable of filtered task array
   */
  getTasksByRole(
    encounterId: string,
    role: string
  ): Observable<AgentTaskResponse[]> {
    return this.http
      .get<AgentTaskResponse[]>(
        `${this.baseUrl}/encounters/${encounterId}/tasks?role=${role}`
      )
      .pipe(
        retry(2),
        catchError(this._handleError)
      );
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _handleError(error: HttpErrorResponse): Observable<never> {
    let errorMessage = 'An unknown error occurred';

    if (error.error instanceof ErrorEvent) {
      // Client-side or network error
      errorMessage = `Network error: ${error.error.message}`;
    } else {
      // Backend returned an unsuccessful response code
      errorMessage = `Server error ${error.status}: ${error.error?.detail || error.message}`;
    }

    console.error('EncounterTasksApiService error:', errorMessage);
    return throwError(() => new Error(errorMessage));
  }
}
