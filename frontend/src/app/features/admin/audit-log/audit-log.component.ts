import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { finalize } from 'rxjs';

import { AdminUsersApiService } from '../services/admin-users-api.service';

interface AuditLogViewEntry {
  time: string;
  date: string;
  user: string;
  action: string;
  displayAction: string;
  targetHtml: string;
}

/**
 * AuditLogComponent — matches Hi-Fi wireframe SCR-011a.
 *
 * Features:
 *   - Date, user, and event-type filters
 *   - Color-coded action badges
 *   - PHI masked entries
 *   - Export CSV placeholder
 */
@Component({
  selector: 'app-audit-log',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './audit-log.component.html',
  styleUrl: './audit-log.component.scss',
})
export class AuditLogComponent implements OnInit {
  private readonly api = inject(AdminUsersApiService);

  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);
  readonly total = signal<number>(0);

  readonly dateFilter = signal<string>('all');
  readonly userFilter = signal<string>('all');
  readonly actionFilter = signal<string>('all');

  readonly actionOptions = signal<string[]>(['all', 'read', 'write', 'create', 'update', 'delete', 'approve', 'resolve', 'reject']);
  readonly userOptions = signal<string[]>(['all', 'nurse', 'physician', 'pharmacist', 'bed_manager', 'admin', 'system']);

  readonly allEntries = signal<AuditLogViewEntry[]>([]);

  readonly filteredEntries = computed(() => {
    const days = this.dateFilter();
    const user = this.userFilter();
    const action = this.actionFilter();

    const cutoff =
      days === 'all'
        ? null
        : new Date(Date.now() - parseInt(days, 10) * 24 * 60 * 60 * 1000);

    return this.allEntries().filter((entry) => {
      const entryDate = new Date(entry.date + 'T00:00:00');
      const dateMatch = !cutoff || entryDate >= cutoff;
      const userMatch = user === 'all' || entry.user.toLowerCase() === user.toLowerCase();
      const actionMatch = action === 'all' || entry.action.toLowerCase() === action.toLowerCase();
      return dateMatch && userMatch && actionMatch;
    });
  });

  ngOnInit(): void {
    this.loadAuditLog();
  }

  loadAuditLog(): void {
    this.loading.set(true);
    this.error.set(null);

    this.api
      .getAuditLog({})
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (response) => {
          this.total.set(response.total);
          this.allEntries.set(response.items.map((entry) => this.mapToViewEntry(entry)));
        },
        error: () => this.error.set('Failed to load audit log. Please try again.'),
      });
  }

  private mapToViewEntry(entry: {
    id: string;
    action: string;
    resource_type: string;
    resource_id: string;
    created_at: string;
    user_id?: string | null;
    user_role?: string | null;
    ip_address?: string | null;
    user_agent?: string | null;
    endpoint?: string | null;
  }): AuditLogViewEntry {
    const createdAt = new Date(entry.created_at);
    const time = isNaN(createdAt.getTime())
      ? entry.created_at
      : createdAt.toLocaleString('en-CA', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        });
    const date = time.split(' ')[0] ?? '';
    const user = entry.user_role ?? 'system';
    const action = entry.action.toUpperCase();
    const displayAction = action;
    const targetHtml = `${entry.resource_type} <strong>${entry.resource_id}</strong>`;

    return { time, date, user, action, displayAction, targetHtml };
  }

  applyFilters(): void {
    // Reactive signals already filter the list automatically.
    // Force a re-evaluation by touching the signals so dependent computed values refresh.
    this.dateFilter.set(this.dateFilter());
    this.userFilter.set(this.userFilter());
    this.actionFilter.set(this.actionFilter());
  }

  exportCsv(): void {
    // Wireframe only — in production this would call the audit export API
  }

  getActionClass(action: string): string {
    const normalized = action.toLowerCase();
    switch (normalized) {
      case 'read':
        return 'read';
      case 'write':
      case 'update':
      case 'create':
        return 'write';
      case 'sign':
      case 'approve':
      case 'resolve':
      case 'reject':
        return 'sign';
      case 'delete':
        return 'delete';
      case 'login':
        return 'login';
      default:
        return 'default';
    }
  }
}
