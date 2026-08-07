import {
  Component,
  ElementRef,
  HostListener,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatBadgeModule } from '@angular/material/badge';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { Router } from '@angular/router';

import { ThemeService } from '@core/theme/theme.service';
import { AuthService } from '@core/auth/auth.service';
import { NotificationService } from '@core/notifications/notification.service';
import { NotificationPanelComponent } from '@shared/components';
import { AppNotification } from '@core/models';

/**
 * HeaderComponent — Dashboard header with user info, notifications, and theme toggle.
 *
 * Features:
 *   - User avatar and display name
 *   - Notifications bell with dropdown panel (UXR-021)
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
    NotificationPanelComponent,
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
})
export class HeaderComponent {
  private readonly theme = inject(ThemeService);
  private readonly auth = inject(AuthService);
  private readonly notificationService = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly elementRef = inject(ElementRef);

  readonly isDarkMode = this.theme.isDarkMode;
  readonly currentUser = this.auth.currentUser;
  readonly notifications = this.notificationService.notifications;
  readonly unreadCount = this.notificationService.unreadCount;
  readonly isNotificationPanelOpen = signal(false);

  /** Close the notification panel when clicking outside the header. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as Node;
    if (!this.elementRef.nativeElement.contains(target)) {
      this.isNotificationPanelOpen.set(false);
    }
  }

  toggleNotificationPanel(): void {
    this.isNotificationPanelOpen.update((open) => !open);
    // Mark all as read when the panel is opened
    if (this.isNotificationPanelOpen()) {
      this.notificationService.markAllAsRead();
    }
  }

  closeNotificationPanel(): void {
    this.isNotificationPanelOpen.set(false);
  }

  onNotificationClick(notification: AppNotification): void {
    this.closeNotificationPanel();
    if (notification.route) {
      void this.router.navigate([notification.route], {
        queryParams: notification.queryParams,
      });
    }
  }

  onMarkAsRead(id: string): void {
    this.notificationService.markAsRead(id);
  }

  onDismiss(id: string): void {
    this.notificationService.dismiss(id);
  }

  onMarkAllAsRead(): void {
    this.notificationService.markAllAsRead();
  }

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
