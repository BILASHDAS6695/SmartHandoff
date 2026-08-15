/**
 * AdminUsersApiService — typed HTTP client for the /api/v1/admin/users API.
 *
 * Provides dynamic user management for the admin panel: list, create,
 * update, disable (deprovision), and re-enable staff accounts.
 *
 * US-061 (dynamic user management)
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env/environment';

export interface AdminUser {
  id: string;
  full_name: string;
  email: string;
  role: string;
  unit?: string;
  is_active: boolean;
  deprovisioned_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserListResponse {
  users: AdminUser[];
  total: number;
}

export interface CreateUserRequest {
  email: string;
  full_name: string;
  role: string;
  unit?: string;
}

export interface UpdateUserRequest {
  email?: string;
  full_name?: string;
  role?: string;
  unit?: string;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  created_at: string;
  user_id?: string | null;
  user_role?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  endpoint?: string | null;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface BulkRoleAssignRequest {
  user_ids: string[];
  role: string;
}

export interface BulkRoleAssignResult {
  user_id: string;
  previous_role: string;
  new_role: string;
}

export interface BulkRoleAssignResponse {
  assigned: BulkRoleAssignResult[];
  not_found: string[];
  total_requested: number;
  total_assigned: number;
}

export interface RoleNormalizeResult {
  user_id: string;
  previous_role: string;
  new_role: string;
}

export interface RoleNormalizeResponse {
  normalized: RoleNormalizeResult[];
  already_standard: string[];
  unrecognized: RoleNormalizeResult[];
  total_normalized: number;
  total_already_standard: number;
  total_unrecognized: number;
}

@Injectable({ providedIn: 'root' })
export class AdminUsersApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/admin/users`;
  private readonly auditUrl = `${environment.apiBaseUrl}/api/v1/admin/audit`;

  /**
   * Fetch all staff accounts from the backend.
   */
  getUsers(): Observable<AdminUserListResponse> {
    return this.http.get<AdminUserListResponse>(this.baseUrl);
  }

  /**
   * Create a new staff account.
   */
  createUser(user: CreateUserRequest): Observable<AdminUser> {
    return this.http.post<AdminUser>(this.baseUrl, user);
  }

  /**
   * Update an existing staff account.
   */
  updateUser(userId: string, user: UpdateUserRequest): Observable<AdminUser> {
    return this.http.patch<AdminUser>(`${this.baseUrl}/${userId}`, user);
  }

  /**
   * Disable/deprovision a staff account. Active JWTs are revoked.
   */
  disableUser(userId: string): Observable<{ message: string; user_id: string }> {
    return this.http.delete<{ message: string; user_id: string }>(`${this.baseUrl}/${userId}`);
  }

  /**
   * Re-enable a previously deprovisioned staff account.
   */
  reenableUser(userId: string): Observable<AdminUser> {
    return this.http.post<AdminUser>(`${this.baseUrl}/${userId}/re-enable`, {});
  }

  /**
   * Fetch paginated, filtered audit log entries from the backend.
   */
  getAuditLog(params: {
    page?: number;
    pageSize?: number;
    from?: string;
    to?: string;
    userId?: string;
    action?: string;
  }): Observable<AuditLogPage> {
    const httpParams: Record<string, string> = {
      page: (params.page ?? 1).toString(),
      page_size: (params.pageSize ?? 50).toString(),
    };
    if (params.from) httpParams['from'] = params.from;
    if (params.to) httpParams['to'] = params.to;
    if (params.userId) httpParams['user_id'] = params.userId;
    if (params.action) httpParams['action'] = params.action;

    return this.http.get<AuditLogPage>(this.auditUrl, { params: httpParams });
  }

  /**
   * Export filtered audit log entries as a CSV blob.
   */
  exportAuditCsv(params: {
    from?: string;
    to?: string;
    userId?: string;
    action?: string;
  }): Observable<Blob> {
    const httpParams: Record<string, string> = {};
    if (params.from) httpParams['from'] = params.from;
    if (params.to) httpParams['to'] = params.to;
    if (params.userId) httpParams['user_id'] = params.userId;
    if (params.action) httpParams['action'] = params.action;

    return this.http.get(`${this.auditUrl}/export/csv`, {
      params: httpParams,
      responseType: 'blob',
    });
  }

  /**
   * Bulk assign a role to multiple users.
   */
  bulkAssignRoles(request: BulkRoleAssignRequest): Observable<BulkRoleAssignResponse> {
    return this.http.post<BulkRoleAssignResponse>(`${this.baseUrl}/bulk-assign-roles`, request);
  }

  /**
   * Normalize legacy/non-standard roles to standard RBAC roles.
   */
  normalizeRoles(): Observable<RoleNormalizeResponse> {
    return this.http.post<RoleNormalizeResponse>(`${this.baseUrl}/normalize-roles`, {});
  }
}
