/**
 * NotificationPanelComponent — dropdown panel for the header notification bell.
 *
 * Renders a list of AppNotification items, supports mark-as-read, dismiss,
 * and click-through navigation. Intended to be toggled by HeaderComponent.
 *
 * UXR-021 Notification Bell + Badge
 */
import {
  Component,
  EventEmitter,
  HostBinding,
  HostListener,
  Input,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';

import { AppNotification } from '@core/models';

@Component({
  selector: 'app-notification-panel',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatIconModule,
    MatButtonModule,
    MatDividerModule,
  ],
  templateUrl: './notification-panel.component.html',
  styleUrl: './notification-panel.component.scss',
})
export class NotificationPanelComponent {
  /** Whether the panel is visible. Controlled by the parent trigger. */
  @HostBinding('class.open') @Input() isOpen = false;

  /** Notifications to display, newest first. */
  @Input() notifications: AppNotification[] = [];

  /** Total unread count (also shown inside the panel header). */
  @Input() unreadCount = 0;

  /** Emitted when a single notification is clicked. */
  @Output() readonly notificationClick = new EventEmitter<AppNotification>();

  /** Emitted when a single notification should be marked as read. */
  @Output() readonly markAsRead = new EventEmitter<string>();

  /** Emitted when a single notification should be dismissed. */
  @Output() readonly dismiss = new EventEmitter<string>();

  /** Emitted when the user marks all notifications as read. */
  @Output() readonly markAllAsRead = new EventEmitter<void>();

  /** Emitted when the panel should close (e.g. Escape key or outside click). */
  @Output() readonly closePanel = new EventEmitter<void>();

  /** Close the panel when the user presses Escape. */
  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.isOpen) {
      this.closePanel.emit();
    }
  }

  trackById(_index: number, notification: AppNotification): string {
    return notification.id;
  }

  getToneIcon(tone: AppNotification['tone']): string {
    const map: Record<AppNotification['tone'], string> = {
      info: 'info',
      warning: 'warning',
      error: 'error',
      success: 'check_circle',
    };
    return map[tone];
  }

  getToneClass(tone: AppNotification['tone']): string {
    return `tone-${tone}`;
  }

  onNotificationClick(notification: AppNotification): void {
    if (!notification.read) {
      this.markAsRead.emit(notification.id);
    }
    this.notificationClick.emit(notification);
  }

  onMarkAll(): void {
    this.markAllAsRead.emit();
  }

  onDismiss(event: MouseEvent, id: string): void {
    event.stopPropagation();
    this.dismiss.emit(id);
  }
}
