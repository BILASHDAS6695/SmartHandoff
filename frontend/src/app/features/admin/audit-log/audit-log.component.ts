import { Component, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

interface AuditLogEntry {
  time: string;
  date: string;
  user: string;
  action: 'READ' | 'WRITE' | 'SIGN' | 'LOGIN';
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
export class AuditLogComponent {
  readonly dateFilter = signal<string>('7');
  readonly userFilter = signal<string>('all');
  readonly actionFilter = signal<string>('all');

  readonly allEntries = signal<AuditLogEntry[]>([
    {
      time: '2026-07-14 14:32',
      date: '2026-07-14',
      user: 'n.smith',
      action: 'READ',
      targetHtml: 'Patient encounter <strong>#2041</strong> (MRN: <span class="masked">●●●●●●</span>)',
    },
    {
      time: '2026-07-14 14:30',
      date: '2026-07-14',
      user: 'd.chen',
      action: 'SIGN',
      targetHtml: 'Document <strong>#8812</strong> — Discharge Summary',
    },
    {
      time: '2026-07-14 14:28',
      date: '2026-07-14',
      user: 'm.phil',
      action: 'WRITE',
      targetHtml: 'Medication reconciliation <strong>#5501</strong> — Alert resolved',
    },
    {
      time: '2026-07-14 14:15',
      date: '2026-07-14',
      user: 'c.johnson',
      action: 'WRITE',
      targetHtml: 'Bed assignment — Bed <strong>4W-03</strong> assigned to encounter #2045',
    },
    {
      time: '2026-07-14 09:10',
      date: '2026-07-14',
      user: 'd.chen',
      action: 'LOGIN',
      targetHtml: 'SSO authentication — MFA verified — IP: <span class="masked">●●●.●.●.●</span>',
    },
    {
      time: '2026-07-14 08:55',
      date: '2026-07-14',
      user: 'admin',
      action: 'WRITE',
      targetHtml: 'User <strong>t.roberts</strong> disabled and sessions revoked',
    },
    {
      time: '2026-07-14 08:32',
      date: '2026-07-14',
      user: 'n.smith',
      action: 'LOGIN',
      targetHtml: 'SSO authentication — MFA verified — IP: <span class="masked">●●●.●.●.●</span>',
    },
    {
      time: '2026-07-13 19:20',
      date: '2026-07-13',
      user: 'm.phil',
      action: 'READ',
      targetHtml: 'Patient encounter <strong>#2038</strong> medication history',
    },
  ]);

  readonly filteredEntries = computed(() => {
    const user = this.userFilter();
    const action = this.actionFilter();
    return this.allEntries().filter((entry) => {
      const userMatch = user === 'all' || entry.user === user;
      const actionMatch = action === 'all' || entry.action === action;
      return userMatch && actionMatch;
    });
  });

  applyFilters(): void {
    // Filtering is reactive via computed signal; this method exists for UX parity.
  }

  exportCsv(): void {
    // Wireframe only — in production this would call the audit export API
  }

  getActionClass(action: string): string {
    switch (action) {
      case 'READ':
        return 'read';
      case 'WRITE':
        return 'write';
      case 'SIGN':
        return 'sign';
      case 'LOGIN':
        return 'login';
      default:
        return '';
    }
  }
}
