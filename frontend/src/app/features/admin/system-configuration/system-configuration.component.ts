import { Component, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

interface ToggleSetting {
  key: string;
  label: string;
  desc: string;
  enabled: boolean;
}

interface SelectSetting {
  key: string;
  label: string;
  desc: string;
  value: string;
  options: string[];
}

interface TextSetting {
  key: string;
  label: string;
  desc: string;
  value: string;
}

interface ConfigSection {
  title: string;
  toggles?: ToggleSetting[];
  selects?: SelectSetting[];
  texts?: TextSetting[];
}

/**
 * SystemConfigurationComponent — matches Hi-Fi wireframe SCR-011b.
 *
 * Features:
 *   - Grouped configuration cards (General, Security, Integrations, Retention)
 *   - Toggle and input controls with pending-change tracking
 *   - Save Changes action (wireframe parity)
 */
@Component({
  selector: 'app-system-configuration',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './system-configuration.component.html',
  styleUrls: ['./system-configuration.component.scss'],
})
export class SystemConfigurationComponent {
  readonly sections = signal<ConfigSection[]>([
    {
      title: 'General Settings',
      texts: [
        {
          key: 'hospitalName',
          label: 'Hospital Name',
          desc: 'Display name used in emails, PDF headers and portal.',
          value: 'Metropolitan General Hospital',
        },
      ],
      selects: [
        {
          key: 'timeZone',
          label: 'Default Time Zone',
          desc: 'Used for audit timestamps and scheduled tasks.',
          value: 'Eastern Time (ET)',
          options: ['Eastern Time (ET)', 'Central Time (CT)', 'Mountain Time (MT)', 'Pacific Time (PT)'],
        },
        {
          key: 'sessionTimeout',
          label: 'Session Timeout',
          desc: 'Idle minutes before automatic sign-out.',
          value: '30 minutes',
          options: ['15 minutes', '30 minutes', '60 minutes', '120 minutes'],
        },
      ],
    },
    {
      title: 'Security & Compliance',
      toggles: [
        {
          key: 'mfa',
          label: 'Require MFA for SSO',
          desc: 'Enforce multi-factor authentication for all staff logins.',
          enabled: true,
        },
        {
          key: 'maskMrn',
          label: 'Mask MRN by Default',
          desc: 'Hide MRN values until the user clicks the reveal icon.',
          enabled: true,
        },
      ],
      selects: [
        {
          key: 'minPassword',
          label: 'Minimum Password Length',
          desc: 'Applies to local service accounts only.',
          value: '12 characters',
          options: ['8 characters', '12 characters', '16 characters'],
        },
      ],
    },
    {
      title: 'Integrations',
      texts: [
        {
          key: 'fhirEndpoint',
          label: 'FHIR R4 Endpoint',
          desc: 'Base URL for patient data synchronization.',
          value: 'https://fhir.hospital.org/r4',
        },
      ],
      selects: [
        {
          key: 'emailProvider',
          label: 'Email Notification Provider',
          desc: 'Service used for patient portal and alert emails.',
          value: 'SendGrid',
          options: ['SendGrid', 'Amazon SES', 'SMTP'],
        },
      ],
      toggles: [
        {
          key: 'aiMonitoring',
          label: 'AI Agent Monitoring',
          desc: 'Enable real-time agent task queue and retry logic.',
          enabled: true,
        },
      ],
    },
    {
      title: 'Data Retention',
      selects: [
        {
          key: 'auditRetention',
          label: 'Audit Log Retention',
          desc: 'Months before audit records are archived.',
          value: '12 months',
          options: ['6 months', '12 months', '24 months', 'Indefinite'],
        },
        {
          key: 'messageRetention',
          label: 'Patient Message Retention',
          desc: 'Months to keep portal chat history.',
          value: '12 months',
          options: ['3 months', '6 months', '12 months'],
        },
      ],
    },
  ]);

  readonly hasChanges = computed(() => {
    // Placeholder: in a real implementation compare against persisted snapshot.
    return true;
  });

  toggle(section: ConfigSection, item: ToggleSetting): void {
    item.enabled = !item.enabled;
    // Trigger reactivity for nested object
    this.sections.set([...this.sections()]);
  }

  saveChanges(): void {
    // Wireframe parity — would call settings API in production
  }
}
