import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatSelectModule } from '@angular/material/select';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { finalize, firstValueFrom } from 'rxjs';

import { AdminUsersApiService, AdminUser, AuditLogEntry, BulkRoleAssignResponse } from '../services/admin-users-api.service';
import { ToastService } from '@core/notifications/toast.service';
import { UserDialogComponent, UserDialogData } from './user-dialog/user-dialog.component';

/** Maps backend role strings to UI display labels. */
const ROLE_DISPLAY_NAMES: Record<string, string> = {
  nurse: 'Nurse',
  physician: 'Physician',
  pharmacist: 'Pharmacist',
  bed_manager: 'BedManager',
  admin: 'Admin',
};

/**
 * Admin Panel Component — matches Hi-Fi wireframe SCR-011.
 *
 * User Management tab is backed by /api/v1/admin/users (US-061).
 */
@Component({
  selector: 'app-admin-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, MatSelectModule, MatDialogModule],
  templateUrl: './admin-panel.component.html',
  styleUrl: './admin-panel.component.scss',
})
export class AdminPanelComponent implements OnInit {
  private readonly dialog = inject(MatDialog);
  private readonly api = inject(AdminUsersApiService);
  private readonly toast = inject(ToastService);

  readonly activeTab = signal<string>('User Management');
  readonly adminTabs = signal<string[]>(['User Management', 'Audit Log', 'System Configuration']);

  readonly users = signal<AdminUser[]>([]);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  readonly auditLog = signal<AuditLogEntry[]>([]);
  readonly auditLoading = signal<boolean>(false);
  readonly auditError = signal<string | null>(null);
  readonly auditTotal = signal<number>(0);

  // User Management filters
  readonly userSearch = signal<string>('');
  readonly userRoleFilter = signal<string>('all');
  readonly userStatusFilter = signal<string>('all');
  readonly roleFilters = signal<string[]>(['all', 'nurse', 'physician', 'pharmacist', 'bed_manager', 'admin']);
  readonly statusFilters = signal<string[]>(['all', 'active', 'inactive']);

  // Bulk role assignment state
  readonly selectedUserIds = signal<Set<string>>(new Set());
  readonly bulkRoleTarget = signal<string>('');
  readonly bulkAssignLoading = signal<boolean>(false);
  readonly normalizeLoading = signal<boolean>(false);

  readonly filteredUsers = computed(() => {
    const search = this.userSearch().trim().toLowerCase();
    const role = this.userRoleFilter();
    const status = this.userStatusFilter();

    return this.users().filter((user) => {
      const matchesSearch =
        !search ||
        user.full_name.toLowerCase().includes(search) ||
        user.email.toLowerCase().includes(search);
      const matchesRole = role === 'all' || user.role === role;
      const matchesStatus =
        status === 'all' ||
        (status === 'active' && this.isUserActive(user)) ||
        (status === 'inactive' && !this.isUserActive(user));
      return matchesSearch && matchesRole && matchesStatus;
    });
  });

  readonly selectedDateFilter = signal<string>('Last 7 days');
  readonly selectedUserFilter = signal<string>('All Users');
  readonly selectedEventFilter = signal<string>('All Event Types');

  readonly dateFilters = signal<string[]>(['Last 7 days', 'Last 30 days']);
  readonly userFilters = signal<string[]>(['All Users', 'd.chen', 'n.smith']);
  readonly eventFilters = signal<string[]>(['All Event Types', 'read', 'write', 'sign', 'login']);

  ngOnInit(): void {
    this.loadUsers();
  }

  setTab(tab: string): void {
    const previous = this.activeTab();
    this.activeTab.set(tab);
    if (tab === 'Audit Log' && previous !== 'Audit Log') {
      this.loadAuditLog();
    }
    if (tab === 'User Management' && previous !== 'User Management') {
      this.loadUsers();
    }
  }

  loadAuditLog(): void {
    this.auditLoading.set(true);
    this.auditError.set(null);

    this.api
      .getAuditLog()
      .pipe(finalize(() => this.auditLoading.set(false)))
      .subscribe({
        next: (response) => {
          this.auditLog.set(response.items);
          this.auditTotal.set(response.total);
        },
        error: () => this.auditError.set('Failed to load audit log. Please try again.'),
      });
  }

  loadUsers(): void {
    this.loading.set(true);
    this.error.set(null);

    this.api
      .getUsers()
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (response) => this.users.set(response.users),
        error: () => this.error.set('Failed to load users. Please try again.'),
      });
  }

  getRoleClass(role: string): string {
    switch (role) {
      case 'nurse': return 'nurse';
      case 'physician': return 'physician';
      case 'pharmacist': return 'pharmacist';
      case 'bed_manager': return 'bedmgr';
      case 'admin': return 'admin';
      default: return 'nurse';
    }
  }

  displayRole(role: string): string {
    return ROLE_DISPLAY_NAMES[role] ?? role;
  }

  isUserActive(user: AdminUser): boolean {
    return user.is_active && !user.deprovisioned_at;
  }

  getStatusClass(user: AdminUser): string {
    return this.isUserActive(user) ? 'active' : 'inactive';
  }

  addUser(): void {
    const dialogRef = this.dialog.open(UserDialogComponent, {
      width: '480px',
      autoFocus: false,
      data: { mode: 'add' } satisfies UserDialogData,
    });

    dialogRef.afterClosed().subscribe(async (result: Partial<AdminUser> | undefined) => {
      if (!result) return;

      try {
        const created = await firstValueFrom(
          this.api.createUser({
            email: result.email!,
            full_name: result.full_name!,
            role: result.role!,
            unit: result.unit,
          })
        );
        this.users.update((list) => [...list, created]);
        this.toast.success(`User ${created.full_name} created.`);
      } catch {
        this.toast.error('Failed to create user.');
      }
    });
  }

  editUser(user: AdminUser): void {
    const dialogRef = this.dialog.open(UserDialogComponent, {
      width: '480px',
      autoFocus: false,
      data: { mode: 'edit', user } satisfies UserDialogData,
    });

    dialogRef.afterClosed().subscribe(async (result: Partial<AdminUser> | undefined) => {
      if (!result) return;

      const payload: { email?: string; full_name?: string; role?: string; unit?: string } = {};
      if (result.email !== undefined) payload.email = result.email;
      if (result.full_name !== undefined) payload.full_name = result.full_name;
      if (result.role !== undefined) payload.role = result.role;
      if (result.unit !== undefined) payload.unit = result.unit;

      try {
        const updated = await firstValueFrom(this.api.updateUser(user.id, payload));
        this.users.update((list) => list.map((u) => (u.id === updated.id ? updated : u)));
        this.toast.success(`User ${updated.full_name} updated.`);
      } catch {
        this.toast.error('Failed to update user.');
      }
    });
  }

  async toggleUserStatus(user: AdminUser): Promise<void> {
    const active = this.isUserActive(user);

    try {
      if (active) {
        await firstValueFrom(this.api.disableUser(user.id));
        this.toast.success(`User ${user.full_name} disabled.`);
      } else {
        await firstValueFrom(this.api.reenableUser(user.id));
        this.toast.success(`User ${user.full_name} re-enabled.`);
      }
      await this.refreshUser(user.id);
    } catch {
      this.toast.error(`Failed to ${active ? 'disable' : 're-enable'} user.`);
    }
  }

  private refreshUser(userId: string): void {
    this.api.getUsers().subscribe({
      next: (response) => this.users.set(response.users),
      error: () => this.toast.error('Failed to refresh user list.'),
    });
  }

  // ── Bulk role assignment ─────────────────────────────────────────────────

  isSelected(userId: string): boolean {
    return this.selectedUserIds().has(userId);
  }

  toggleSelection(userId: string): void {
    this.selectedUserIds.update((set) => {
      const next = new Set(set);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  }

  toggleSelectAll(): void {
    const visibleIds = this.filteredUsers().map((u) => u.id);
    const allSelected = visibleIds.every((id) => this.selectedUserIds().has(id));
    this.selectedUserIds.update((set) => {
      const next = new Set(set);
      if (allSelected) {
        visibleIds.forEach((id) => next.delete(id));
      } else {
        visibleIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  isAllSelected(): boolean {
    const visibleIds = this.filteredUsers().map((u) => u.id);
    return visibleIds.length > 0 && visibleIds.every((id) => this.selectedUserIds().has(id));
  }

  async applyBulkRole(): Promise<void> {
    const role = this.bulkRoleTarget();
    const ids = Array.from(this.selectedUserIds());
    if (!role || ids.length === 0) {
      this.toast.error('Select at least one user and a target role.');
      return;
    }

    this.bulkAssignLoading.set(true);
    try {
      const result = await firstValueFrom(
        this.api.bulkAssignRoles({ user_ids: ids, role })
      );
      this.selectedUserIds.set(new Set());
      this.bulkRoleTarget.set('');
      this.loadUsers();
      this.toast.success(`Assigned ${role} to ${result.total_assigned} user(s).`);
    } catch {
      this.toast.error('Failed to assign roles.');
    } finally {
      this.bulkAssignLoading.set(false);
    }
  }

  async normalizeRoles(): Promise<void> {
    this.normalizeLoading.set(true);
    try {
      const result = await firstValueFrom(this.api.normalizeRoles());
      this.loadUsers();
      if (result.total_unrecognized > 0) {
        this.toast.success(
          `Normalized ${result.total_normalized} role(s). ${result.total_unrecognized} unrecognized role(s) left unchanged.`
        );
      } else {
        this.toast.success(`Normalized ${result.total_normalized} role(s).`);
      }
    } catch {
      this.toast.error('Failed to normalize roles.');
    } finally {
      this.normalizeLoading.set(false);
    }
  }

  applyAuditFilters(): void {
    // Placeholder for audit filter action
  }

  exportAuditCsv(): void {
    // Placeholder for export action
  }
}
