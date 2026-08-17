import {
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
  OnInit,
  OnDestroy,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatIcon } from '@angular/material/icon';
import { Subscription } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { DocumentQueueStore } from '../../../documents/store/document-queue.store';
import { DASHBOARD_SECTION_ROLES, Role } from '@core/models';
import { PatientApiService } from '../../../patients/services/patient-api.service';
import { EncountersApiService } from '@core/api';

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
export class SidebarComponent implements OnInit, OnDestroy {
  @Output() readonly linkClicked = new EventEmitter<void>();

  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly queueStore = inject(DocumentQueueStore);
  private readonly patientApi = inject(PatientApiService);
  private readonly encountersApi = inject(EncountersApiService);

  readonly uniquePatientCount = signal<number>(0);
  readonly encounterCount = signal<number>(0);
  private readonly subs = new Subscription();

  private readonly allSections = computed<MenuSection[]>(() => [
    {
      title: 'Navigation',
      items: [
        { icon: 'dashboard', label: 'Dashboard', route: '/dashboard' },
        { icon: 'people', label: 'Patients', route: '/patients', badge: () => this.uniquePatientCount(), roles: [Role.Admin] },
        { icon: 'folder_copy', label: 'Encounters', route: '/encounters', badge: () => this.encounterCount() },
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
  ]);

  readonly sections = computed<MenuSection[]>(() => {
    const userRole = this.auth.currentUser()?.role?.toLowerCase() ?? '';
    return this.allSections()
      .map((section) => ({
        ...section,
        items: section.items.filter(
          (item) => !item.roles || item.roles.includes(userRole),
        ),
      }))
      .filter((section) => section.items.length > 0);
  });

  ngOnInit(): void {
    const user = this.auth.currentUser();
    const unit = user?.units?.[0] ?? '';

    this.subs.add(
      this.patientApi.getPatients({ unit, page: 1, page_size: 1, unique: true })
        .subscribe(response => this.uniquePatientCount.set(response.total ?? 0)),
    );

    this.subs.add(
      this.encountersApi.listEncounters({ unit, page: 1, page_size: 1 })
        .subscribe(response => this.encounterCount.set(response.total ?? 0)),
    );
  }

  ngOnDestroy(): void {
    this.subs.unsubscribe();
  }

  onLinkClick(): void {
    this.linkClicked.emit();
  }

  isActive(route: string): boolean {
    return this.router.isActive(route, true);
  }
}
