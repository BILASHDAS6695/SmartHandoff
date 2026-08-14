import { Component, EventEmitter, Output, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatIcon } from '@angular/material/icon';
import { AuthService } from '@core/auth/auth.service';
import { DocumentQueueStore } from '../../../documents/store/document-queue.store';
import { DASHBOARD_SECTION_ROLES, Role } from '@core/models';

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
  roles?: string[];
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
  private readonly auth = inject(AuthService);
  private readonly queueStore = inject(DocumentQueueStore);

  private readonly allSections: MenuSection[] = [
    {
      title: 'Navigation',
      items: [
        { icon: 'dashboard', label: 'Dashboard', route: '/dashboard' },
        { icon: 'people', label: 'Patients', route: '/patients', badge: () => 142 },
        { icon: 'assignment_add', label: 'Register Encounter', route: '/patients/register' },
        { icon: 'assignment', label: 'Task Monitor', route: '/tasks', roles: [Role.Nurse, Role.Physician, Role.Admin] },
      ],
    },
    {
      title: 'Account',
      items: [
        { icon: 'switch_account', label: 'Switch Role', route: '/switch-role', roles: [Role.Admin] },
      ],
    },
    {
      title: 'Role-Gated',
      items: [
        { icon: 'hotel', label: 'Bed Board', route: '/beds', tag: 'BedMgr only', roles: ['bed_manager', 'admin'] },
        { icon: 'analytics', label: 'Analytics', route: '/analytics', tag: 'Manager only', roles: ['admin'] },
        { icon: 'admin_panel_settings', label: 'Admin', route: '/admin', tag: 'Admin only', roles: ['admin'] },
      ],
    },
  ];

  readonly sections = computed<MenuSection[]>(() => {
    const userRole = this.auth.currentUser()?.role?.toLowerCase() ?? '';
    return this.allSections
      .map((section) => ({
        ...section,
        items: section.items.filter(
          (item) => !item.roles || item.roles.includes(userRole),
        ),
      }))
      .filter((section) => section.items.length > 0);
  });

  onLinkClick(): void {
    this.linkClicked.emit();
  }

  isActive(route: string): boolean {
    return this.router.isActive(route, true);
  }
}
