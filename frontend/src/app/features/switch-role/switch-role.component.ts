import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@core/notifications/toast.service';

interface RoleOption {
  id: string;
  title: string;
  description: string;
  icon: string;
  iconColor: string;
  bgColor: string;
}

/**
 * SwitchRoleComponent — Role and unit context switcher matching SCR-013 wireframe.
 *
 * Features:
 *   - Selectable role cards with active-state styling
 *   - Session unit selector
 *   - Cancel / Confirm Switch actions
 */
@Component({
  selector: 'app-switch-role',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './switch-role.component.html',
  styleUrl: './switch-role.component.scss',
})
export class SwitchRoleComponent {
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  readonly roles: RoleOption[] = [
    {
      id: 'Nurse',
      title: 'Nurse',
      description: 'Handoff tasks, patient lists, medication reconciliation.',
      icon: 'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z',
      iconColor: '#4F46E5',
      bgColor: '#EEF2FF',
    },
    {
      id: 'Physician',
      title: 'Physician',
      description: 'Review reconciliations, approve documents, care plans.',
      icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
      iconColor: '#15803D',
      bgColor: '#F0FDF4',
    },
    {
      id: 'Pharmacist',
      title: 'Pharmacist',
      description: 'Drug interaction checks, evidence review, summaries.',
      icon: 'M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z',
      iconColor: '#C2410C',
      bgColor: '#FFF7ED',
    },
    {
      id: 'BedManager',
      title: 'Bed Manager',
      description: 'Bed board, ED alerts, patient routing.',
      icon: 'M5 10l7-7m0 0l7 7m-7-7v18',
      iconColor: '#0D9488',
      bgColor: '#F0FDFA',
    },
    {
      id: 'Admin',
      title: 'Administrator',
      description: 'User management, audit log, system configuration.',
      icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
      iconColor: '#2563EB',
      bgColor: '#EFF6FF',
    },
  ];

  readonly units = ['4-West', '3-North', 'ICU', 'Emergency', 'Surgery'];

  readonly selectedRole = signal<string>('Nurse');
  readonly selectedUnit = signal<string>('4-West');

  readonly currentRole = signal<string>('Nurse');
  readonly currentUnit = signal<string>('4-West');

  constructor() {
    const user = this.auth.currentUser();
    if (user) {
      const role = this.formatRole(user.role);
      this.selectedRole.set(role);
      this.currentRole.set(role);
    }
  }

  private formatRole(role: string): string {
    const map: Record<string, string> = {
      NURSE: 'Nurse',
      PHYSICIAN: 'Physician',
      PHARMACIST: 'Pharmacist',
      BEDMGR: 'BedManager',
      ADMIN: 'Admin',
    };
    return map[role.toUpperCase()] ?? role;
  }

  selectRole(roleId: string): void {
    this.selectedRole.set(roleId);
  }

  onCancel(): void {
    history.back();
  }

  onConfirm(): void {
    const role = this.selectedRole();
    const unit = this.selectedUnit();
    this.currentRole.set(role);
    this.currentUnit.set(unit);
    // Wireframe only — in production this would call the session context API
    this.toast.success(`Switched to ${role} · ${unit}`);
    void this.router.navigate(['/dashboard']);
  }
}
