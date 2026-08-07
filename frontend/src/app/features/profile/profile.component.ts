/**
 * ProfileComponent — User profile page matching SCR-012 wireframe.
 *
 * Features:
 *   - Read-only identity card from JWT claims
 *   - Editable preferences (display name, default unit, phone, toggles)
 *   - Active session list with revoke action
 *   - Change password and sign-out-all-devices dialogs
 */
import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';

import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@core/notifications/toast.service';
import {
  ChangePasswordDialogComponent,
  SignOutAllDialogComponent,
} from './dialogs';

interface UserSession {
  id: string;
  device: string;
  location: string;
  lastActive: string;
  isCurrent: boolean;
  revoked?: boolean;
}

interface UserPreferences {
  displayName: string;
  defaultUnit: string;
  phone: string;
  emailNotifications: boolean;
  pushAlerts: boolean;
  compactCards: boolean;
}

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, FormsModule, MatDialogModule],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
})
export class ProfileComponent {
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly dialog = inject(MatDialog);

  readonly currentUser = this.auth.currentUser;

  readonly units = ['4-West', '3-North', 'ICU', 'Emergency'];

  readonly preferences = signal<UserPreferences>({
    displayName: 'IT Admin',
    defaultUnit: '4-West',
    phone: '+1 (555) 010-2034',
    emailNotifications: true,
    pushAlerts: true,
    compactCards: false,
  });

  private readonly originalDisplayName = 'IT Admin';

  readonly sessions = signal<UserSession[]>([
    {
      id: 'current',
      device: 'Chrome on macOS',
      location: 'New York, NY',
      lastActive: 'Now',
      isCurrent: true,
    },
    {
      id: 'iphone',
      device: 'Safari on iPhone',
      location: 'New York, NY',
      lastActive: '2h ago',
      isCurrent: false,
    },
  ]);

  getUserInitials(): string {
    const user = this.currentUser();
    if (!user) return 'U';
    const email = user.email || '';
    const parts = email.split('@')[0].split('.');
    return parts.map((p) => p[0]?.toUpperCase()).join('').slice(0, 2) || 'U';
  }

  getRoleLabel(): string {
    const role = this.currentUser()?.role ?? 'Staff';
    return role.charAt(0).toUpperCase() + role.slice(1);
  }

  displayName(): string {
    return this.originalDisplayName;
  }

  onSave(): void {
    // Wireframe only — in production this would call the user-preferences API
    this.toast.success('Profile preferences saved');
  }

  onBack(): void {
    history.back();
  }

  revokeSession(sessionId: string): void {
    this.sessions.update((list) =>
      list.map((s) => (s.id === sessionId ? { ...s, revoked: true } as UserSession : s)),
    );
    this.toast.info('Session revoked');
  }

  openChangePassword(): void {
    this.dialog.open(ChangePasswordDialogComponent, {
      width: '420px',
      autoFocus: false,
    });
  }

  openSignOutAll(): void {
    this.dialog.open(SignOutAllDialogComponent, {
      width: '420px',
      autoFocus: false,
    });
  }
}
