import { Component, EventEmitter, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatNavList, MatListItem } from '@angular/material/list';
import { MatIcon } from '@angular/material/icon';
import { MatBadgeModule } from '@angular/material/badge';
import { DocumentQueueStore } from '../../../documents/store/document-queue.store';

/**
 * SidebarComponent — Navigation sidebar for dashboard layout.
 *
 * Features:
 *   - Role-based menu items
 *   - Active route highlighting
 *   - Responsive mobile support
 */
@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterModule, MatNavList, MatListItem, MatIcon, MatBadgeModule],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  @Output() readonly linkClicked = new EventEmitter<void>();

  private readonly queueStore = inject(DocumentQueueStore);

  readonly menuItems = [
    { icon: 'dashboard', label: 'Dashboard', route: '/dashboard' },
    { icon: 'people', label: 'Patients', route: '/patients' },
    { icon: 'hotel', label: 'Beds', route: '/beds' },
    { icon: 'medication', label: 'Medications', route: '/medications' },
    { icon: 'description', label: 'Documents', route: '/documents', badge: () => this.queueStore.count() },
    { icon: 'analytics', label: 'Analytics', route: '/analytics' },
  ];

  onLinkClick(): void {
    this.linkClicked.emit();
  }
}
