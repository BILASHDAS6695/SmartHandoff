import { Component, EventEmitter, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatIcon } from '@angular/material/icon';
import { DocumentQueueStore } from '../../../documents/store/document-queue.store';

interface MenuSection {
  title: string;
  items: MenuItem[];
}

interface MenuItem {
  icon: string;
  label: string;
  route: string;
  badge?: () => number | null;
  tag?: string;
}

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
  imports: [CommonModule, RouterModule, MatIcon],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  @Output() readonly linkClicked = new EventEmitter<void>();

  private readonly router = inject(Router);
  private readonly queueStore = inject(DocumentQueueStore);

  readonly sections: MenuSection[] = [
    {
      title: 'Navigation',
      items: [
        { icon: 'dashboard', label: 'Dashboard', route: '/dashboard' },
        { icon: 'people', label: 'Patients', route: '/patients', badge: () => 142 },
      ],
    },
    {
      title: 'Role-Gated',
      items: [
        { icon: 'hotel', label: 'Bed Board', route: '/beds', tag: 'BedMgr only' },
        { icon: 'analytics', label: 'Analytics', route: '/analytics', tag: 'Manager only' },
        { icon: 'admin_panel_settings', label: 'Admin', route: '/admin', tag: 'Admin only' },
      ],
    },
  ];

  onLinkClick(): void {
    this.linkClicked.emit();
  }

  isActive(route: string): boolean {
    return this.router.isActive(route, true);
  }
}
