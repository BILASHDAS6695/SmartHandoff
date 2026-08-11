import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatSelectModule } from '@angular/material/select';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { finalize, firstValueFrom } from 'rxjs';

import { AdminUsersApiService, AdminUser } from '../services/admin-users-api.service';
import { ToastService } from '@core/notifications/toast.service';
import { UserDialogComponent, UserDialogData } from './user-dialog/user-dialog.component';

interface AuditLogEntry {
  time: string;
  user: string;
  action: string;
  target: string;
}

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

  readonly auditLog = signal<AuditLogEntry[]>([
    { time: '2026-07-14 14:32', user: 'n.smith', action: 'READ', target: 'Patient encounter #2041 (MRN: ●●●●●●)' },
    { time: '2026-07-14 14:30', user: 'd.chen', action: 'SIGN', target: 'Document #8812 — Discharge Summary' },
    { time: '2026-07-14 14:28', user: 'm.phil', action: 'WRITE', target: 'Medication reconciliation #5501 — Alert resolved' },
    { time: '2026-07-14 14:15', user: 'c.johnson', action: 'WRITE', target: 'Bed assignment — Bed 4W-03 assigned to encounter #2045' },
    { time: '2026-07-14 09:10', user: 'd.chen', action: 'LOGIN', target: 'SSO authentication — MFA verified — IP: ●●●.●.●.●' },
  ]);

  readonly selectedDateFilter = signal<string>('Last 7 days');
  readonly selectedUserFilter = signal<string>('All Users');
  readonly selectedEventFilter = signal<string>('All Event Types');

  readonly dateFilters = signal<string[]>(['Last 7 days', 'Last 30 days']);
  readonly userFilters = signal<string[]>(['All Users', 'd.chen', 'n.smith']);
  readonly eventFilters = signal<string[]>(['All Event Types', 'READ', 'WRITE', 'SIGN', 'LOGIN']);

  ngOnInit(): void {
    this.loadUsers();
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

  setTab(tab: string): void {
    this.activeTab.set(tab);
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

  applyAuditFilters(): void {
    // Placeholder for audit filter action
  }

  exportAuditCsv(): void {
    // Placeholder for export action
  }
}
