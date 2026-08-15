import { Component, OnInit, computed, effect, inject, signal } from '@angular/core';
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
  readonly savingUser = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // User pagination
  readonly userPage = signal<number>(1);
  readonly userPageSize = signal<number>(10);

  readonly auditLog = signal<AuditLogEntry[]>([]);
  readonly auditLoading = signal<boolean>(false);
  readonly auditExportLoading = signal<boolean>(false);
  readonly auditError = signal<string | null>(null);
  readonly auditTotal = signal<number>(0);
  readonly auditPage = signal<number>(1);
  readonly auditPageSize = signal<number>(15);
  readonly auditPages = signal<number>(1);

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
  readonly togglingUserId = signal<string | null>(null);

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

  readonly userTotalPages = computed(() =>
    Math.max(1, Math.ceil(this.filteredUsers().length / this.userPageSize()))
  );

  readonly pagedUsers = computed(() => {
    const start = (this.userPage() - 1) * this.userPageSize();
    return this.filteredUsers().slice(start, start + this.userPageSize());
  });

  readonly selectedDateFilter = signal<string>('Last 7 days');
  readonly selectedUserFilter = signal<string>('all');
  readonly selectedEventFilter = signal<string>('all');

  readonly dateFilters = signal<string[]>(['Last 7 days', 'Last 30 days', 'All time']);
  readonly eventFilters = signal<string[]>(['all', 'read', 'write', 'sign', 'login']);

  readonly auditUserOptions = computed(() => {
    const options = [{ id: 'all', label: 'All Users' }];
    for (const user of this.users()) {
      const display = user.full_name || user.email.split('@')[0];
      options.push({ id: user.id, label: display });
    }
    return options;
  });

  constructor() {
    effect(() => {
      // Track user-filter changes, then reset to first page outside the reactive read.
      const _search = this.userSearch();
      const _role = this.userRoleFilter();
      const _status = this.userStatusFilter();
      queueMicrotask(() => this.userPage.set(1));
    });
  }

  ngOnInit(): void {
    this.loadUsers();
  }

  setTab(tab: string): void {
    const previous = this.activeTab();
    this.activeTab.set(tab);
    if (tab === 'User Management' && previous !== 'User Management') {
      this.loadUsers();
    }
    if (tab === 'Audit Log' && previous !== 'Audit Log') {
      if (this.users().length === 0) {
        this.loadUsers();
      }
      this.loadAuditLog();
    }
  }

  loadAuditLog(): void {
    this.auditLoading.set(true);
    this.auditError.set(null);

    const dateRange = this.#auditDateRange(this.selectedDateFilter());
    const userId = this.selectedUserFilter() === 'all' ? undefined : this.selectedUserFilter();
    const action = this.selectedEventFilter() === 'all' ? undefined : this.selectedEventFilter();

    this.api
      .getAuditLog({
        page: this.auditPage(),
        pageSize: this.auditPageSize(),
        from: dateRange.from,
        to: dateRange.to,
        userId,
        action,
      })
      .pipe(finalize(() => this.auditLoading.set(false)))
      .subscribe({
        next: (response) => {
          this.auditLog.set(response.items);
          this.auditTotal.set(response.total);
          this.auditPages.set(response.pages);
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

      this.savingUser.set(true);
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
      } finally {
        this.savingUser.set(false);
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

      this.savingUser.set(true);
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
      } finally {
        this.savingUser.set(false);
      }
    });
  }

  async toggleUserStatus(user: AdminUser): Promise<void> {
    const active = this.isUserActive(user);
    this.togglingUserId.set(user.id);

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
    } finally {
      this.togglingUserId.set(null);
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

  clearSelection(): void {
    this.selectedUserIds.set(new Set());
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
      this.clearSelection();
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

  applyUserFilters(): void {
    this.userPage.set(1);
  }

  applyAuditFilters(): void {
    this.auditPage.set(1);
    this.loadAuditLog();
  }

  #auditDateRange(filter: string): { from?: string; to?: string } {
    const now = new Date();
    const to = now.toISOString();
    if (filter === 'All time') {
      return {};
    }
    let from: string | undefined;
    if (filter === 'Last 7 days') {
      const d = new Date(now);
      d.setDate(d.getDate() - 7);
      from = d.toISOString();
    } else if (filter === 'Last 30 days') {
      const d = new Date(now);
      d.setDate(d.getDate() - 30);
      from = d.toISOString();
    }
    return { from, to };
  }

  setUserPage(page: number): void {
    if (page >= 1 && page <= this.userTotalPages()) {
      this.userPage.set(page);
    }
  }

  setAuditPage(page: number): void {
    if (page >= 1 && page <= this.auditPages()) {
      this.auditPage.set(page);
      this.loadAuditLog();
    }
  }

  async exportAuditCsv(): Promise<void> {
    this.auditExportLoading.set(true);
    try {
      const dateRange = this.#auditDateRange(this.selectedDateFilter());
      const userId = this.selectedUserFilter() === 'all' ? undefined : this.selectedUserFilter();
      const action = this.selectedEventFilter() === 'all' ? undefined : this.selectedEventFilter();

      const blob = await firstValueFrom(
        this.api.exportAuditCsv({ from: dateRange.from, to: dateRange.to, userId, action })
      );

      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      this.toast.success('Audit log exported successfully.');
    } catch {
      this.toast.error('Failed to export audit log. Please try again.');
    } finally {
      this.auditExportLoading.set(false);
    }
  }
}
