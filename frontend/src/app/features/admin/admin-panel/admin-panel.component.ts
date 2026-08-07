import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatSelectModule } from '@angular/material/select';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';

import { UserDialogComponent, UserDialogData } from './user-dialog/user-dialog.component';

export interface AdminUser {
  name: string;
  email: string;
  role: string;
  unit?: string;
  status: 'Active' | 'Inactive';
  lastLogin: string;
}

interface AuditLogEntry {
  time: string;
  user: string;
  action: string;
  target: string;
}

/**
 * Admin Panel Component — matches Hi-Fi wireframe SCR-011.
 */
@Component({
  selector: 'app-admin-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, MatSelectModule, MatDialogModule],
  templateUrl: './admin-panel.component.html',
  styleUrl: './admin-panel.component.scss',
})
export class AdminPanelComponent {
  private readonly dialog = inject(MatDialog);

  readonly activeTab = signal<string>('User Management');
  readonly adminTabs = signal<string[]>(['User Management', 'Audit Log', 'System Configuration']);

  readonly users = signal<AdminUser[]>([
    { name: 'Smith, Nancy', email: 'n.smith@hospital.org', role: 'Nurse', status: 'Active', lastLogin: '2026-07-14 08:32' },
    { name: 'Chen, David', email: 'd.chen@hospital.org', role: 'Physician', status: 'Active', lastLogin: '2026-07-14 09:10' },
    { name: 'Phil, Marcus', email: 'm.phil@hospital.org', role: 'Pharmacist', status: 'Active', lastLogin: '2026-07-14 07:55' },
    { name: 'Johnson, Carol', email: 'c.johnson@hospital.org', role: 'BedManager', status: 'Active', lastLogin: '2026-07-14 06:30' },
    { name: 'Roberts, Tom', email: 't.roberts@hospital.org', role: 'Admin', status: 'Inactive', lastLogin: '2026-06-30 14:20' },
  ]);

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

  setTab(tab: string): void {
    this.activeTab.set(tab);
  }

  getRoleClass(role: string): string {
    switch (role) {
      case 'Nurse': return 'nurse';
      case 'Physician': return 'physician';
      case 'Pharmacist': return 'pharmacist';
      case 'BedManager': return 'bedmgr';
      case 'Admin': return 'admin';
      default: return 'nurse';
    }
  }

  getStatusClass(status: string): string {
    return status === 'Active' ? 'active' : 'inactive';
  }

  addUser(): void {
    const dialogRef = this.dialog.open(UserDialogComponent, {
      width: '480px',
      autoFocus: false,
      data: { mode: 'add' } satisfies UserDialogData,
    });

    dialogRef.afterClosed().subscribe((result: AdminUser | undefined) => {
      if (result) {
        this.users.update((list) => [...list, result]);
      }
    });
  }

  editUser(user: AdminUser): void {
    this.dialog.open(UserDialogComponent, {
      width: '480px',
      autoFocus: false,
      data: { mode: 'edit', user } satisfies UserDialogData,
    });
  }

  toggleUserStatus(user: AdminUser): void {
    user.status = user.status === 'Active' ? 'Inactive' : 'Active';
    this.users.set([...this.users()]);
  }

  applyAuditFilters(): void {
    // Placeholder for audit filter action
  }

  exportAuditCsv(): void {
    // Placeholder for export action
  }
}
