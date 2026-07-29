import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatBadgeModule } from '@angular/material/badge';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';

import { ThemeService } from '@core/theme/theme.service';
import { AuthService } from '@core/auth/auth.service';

/**
 * HeaderComponent — Dashboard header with user info, notifications, and theme toggle.
 *
 * Features:
 *   - User avatar and display name
 *   - Notifications badge
 *   - Dark mode toggle
 *   - Logout button
 */
@Component({
  selector: 'app-header',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
    MatBadgeModule,
    MatMenuModule,
    MatTooltipModule,
    MatDividerModule,
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
})
export class HeaderComponent {
  private readonly theme = inject(ThemeService);
  private readonly auth = inject(AuthService);

  readonly isDarkMode = this.theme.isDarkMode;
  readonly currentUser = this.auth.currentUser;
  readonly notificationCount = 3; // Placeholder — integrate with real notification service

  toggleTheme(): void {
    this.theme.toggleDarkMode();
  }

  logout(): void {
    this.auth.logout();
  }

  getUserInitials(): string {
    const user = this.currentUser();
    if (!user) return 'U';
    // Extract initials from email or name claim
    const email = (user as unknown as Record<string, string>)['email'] || '';
    const parts = email.split('@')[0].split('.');
    return parts.map((p) => p[0]?.toUpperCase()).join('').slice(0, 2) || 'U';
  }
}
