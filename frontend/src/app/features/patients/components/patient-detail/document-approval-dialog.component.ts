import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { BackendDocument } from '@features/documents/services/document-api.service';

export interface DocumentApprovalDialogData {
  doc: BackendDocument;
  title: string;
  meta: string;
  mode: 'review' | 'view';
}

/**
 * DocumentApprovalDialogComponent — AI-assisted clinical document approval modal.
 *
 * Renders patient-specific content returned by the backend document generation
 * service, with a layout tailored to the document type.
 *
 * Wireframe ref: SCR-004 Patient Detail "Pending Approvals" card.
 */
@Component({
  selector: 'app-document-approval-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
  ],
  template: `
    <div class="dialog-header">
      <div class="dialog-header-title">
        <h2 mat-dialog-title id="doc-approval-title">
          {{ isViewMode() ? 'View Document' : 'Review & Approve' }}
        </h2>
        <span class="dialog-subtitle">{{ data.title }}</span>
      </div>
      <button mat-icon-button class="dialog-close" [mat-dialog-close]="null" aria-label="Close dialog">
        <mat-icon>close</mat-icon>
      </button>
    </div>
    <mat-dialog-content class="dialog-content">
      <div class="dialog-meta">
        <span class="meta-pill">{{ data.meta }}</span>
        @if (doc.ai_assisted_label) {
          <span class="ai-badge">
            <mat-icon>auto_awesome</mat-icon>
            AI-Assisted — Review Required
          </span>
        }
      </div>
      <div class="document-preview">
        @if (content(); as c) {
          <h4>{{ sectionTitle() }}</h4>

          <div class="patient-summary">
            <p><strong>Patient:</strong> {{ $any(c).patient?.name ?? '—' }}</p>
            <p><strong>DOB:</strong> {{ $any(c).patient?.date_of_birth ?? '—' }} | <strong>MRN:</strong> {{ $any(c).patient?.mrn ?? '●●●●' }}</p>
            @if ($any(c).encounter?.admission_date) {
              <p><strong>Admission Date:</strong> {{ $any(c).encounter.admission_date }}</p>
            }
          </div>

          @switch (doc.document_type) {
            @case ('discharge_summary') {
              @if ($any(c).inferred_conditions?.length) {
                <p><strong>Primary Diagnosis:</strong> {{ $any(c).inferred_conditions[0].condition }}</p>
              }
              @if ($any(sections()).hospital_course) {
                <p><strong>Hospital Course:</strong> {{ $any(sections()).hospital_course }}</p>
              }
              @if (meds().length) {
                <p><strong>Discharge Medications:</strong></p>
                <ul>
                  @for (med of meds(); track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
              @if (followUps().length) {
                <p><strong>Follow-up:</strong></p>
                <ul>
                  @for (item of followUps(); track $index) {
                    <li>{{ item.instruction }} — {{ item.timeframe }}</li>
                  }
                </ul>
              }
            }
            @case ('medication_reconciliation') {
              @if (reconciliationSummary()) {
                <p><strong>Reconciliation Summary:</strong> {{ reconciliationSummary() }}</p>
              }
              @if ($any(sections()).continued_medications?.length) {
                <p><strong>Continued Medications:</strong></p>
                <ul>
                  @for (med of $any(sections()).continued_medications; track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
              @if ($any(sections()).new_medications?.length) {
                <p><strong>New Medications:</strong></p>
                <ul>
                  @for (med of $any(sections()).new_medications; track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
              @if ($any(sections()).stopped_medications?.length) {
                <p><strong>Stopped Medications:</strong></p>
                <ul>
                  @for (med of $any(sections()).stopped_medications; track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
              @if ($any(sections()).dose_changed_medications?.length) {
                <p><strong>Dose-Changed Medications:</strong></p>
                <ul>
                  @for (med of $any(sections()).dose_changed_medications; track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
              @if ($any(sections()).drug_interactions?.length) {
                <p><strong>Drug Interactions / Alerts:</strong></p>
                <ul>
                  @for (alert of $any(sections()).drug_interactions; track $index) {
                    <li>{{ alert.severity }}: {{ alert.description }}</li>
                  }
                </ul>
              }
            }
            @case ('follow_up_plan') {
              @if ($any(sections()).risk_assessment) {
                <p><strong>Risk Tier:</strong> {{ $any(sections()).risk_assessment.tier }} — follow-up within {{ $any(sections()).risk_assessment.follow_up_within_days }} days</p>
              }
              @if ($any(sections()).appointments?.length) {
                <p><strong>Appointments:</strong></p>
                <ul>
                  @for (appt of $any(sections()).appointments; track $index) {
                    <li>{{ appt.type }} — {{ appt.timeframe }} ({{ appt.reason }})</li>
                  }
                </ul>
              }
              @if ($any(sections()).conditions_to_monitor?.length) {
                <p><strong>Conditions to Monitor:</strong> {{ $any(sections()).conditions_to_monitor.join(', ') }}</p>
              }
            }
            @case ('patient_instructions') {
              @if ($any(sections()).what_happened) {
                <p><strong>What Happened:</strong> {{ $any(sections()).what_happened }}</p>
              }
              @if (meds().length) {
                <p><strong>Your Medications:</strong></p>
                <ul>
                  @for (med of meds(); track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
              @if ($any(sections()).follow_up) {
                <p><strong>Follow-up:</strong> {{ $any(sections()).follow_up }}</p>
              }
              @if ($any(sections()).when_to_seek_help?.length) {
                <p><strong>When to Seek Help:</strong></p>
                <ul>
                  @for (item of $any(sections()).when_to_seek_help; track $index) {
                    <li>{{ item }}</li>
                  }
                </ul>
              }
            }
            @case ('transfer_summary') {
              <p><strong>Current Status:</strong> {{ $any(sections()).current_status ?? '—' }}</p>
              <p><strong>Transfer Reason:</strong> {{ $any(sections()).transfer_reason ?? '—' }}</p>
              @if (meds().length) {
                <p><strong>Active Medications:</strong></p>
                <ul>
                  @for (med of meds(); track trackMed($index, med)) {
                    <li>{{ medLabel(med) }}</li>
                  }
                </ul>
              }
            }
            @case ('care_transition_summary') {
              @if ($any(sections()).coordination_notes) {
                <p><strong>Coordination Notes:</strong> {{ $any(sections()).coordination_notes }}</p>
              }
              @if ($any(sections()).tasks_completed?.length) {
                <p><strong>Tasks Completed:</strong></p>
                <ul>
                  @for (task of $any(sections()).tasks_completed; track $index) {
                    <li>{{ task }}</li>
                  }
                </ul>
              }
              @if ($any(sections()).open_items?.length) {
                <p><strong>Open Items:</strong></p>
                <ul>
                  @for (item of $any(sections()).open_items; track $index) {
                    <li>{{ item }}</li>
                  }
                </ul>
              }
            }
            @default {
              <pre class="raw-content">{{ c | json }}</pre>
            }
          }
        } @else {
          <p class="empty-output">No content available for review.</p>
        }
      </div>
      @if (!isViewMode()) {
        <div class="rejection-panel">
          <mat-form-field class="rejection-reason-field" appearance="outline">
            <mat-label>Rejection reason (required, min 10 characters)</mat-label>
            <textarea
              matInput
              [(ngModel)]="rejectionReason"
              rows="3"
              placeholder="Enter reason for rejection">
            </textarea>
          </mat-form-field>
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions class="dialog-actions" align="end">
      @if (isViewMode()) {
        <button mat-raised-button class="btn-primary" [mat-dialog-close]="null">Close</button>
      } @else {
        <button
          mat-button
          class="btn-reject"
          [mat-dialog-close]="{ action: 'reject', rejection_reason: rejectionReason }"
          [disabled]="!rejectionReason || rejectionReason.length < 10">
          Reject
        </button>
        <button
          mat-raised-button
          class="btn-approve"
          [mat-dialog-close]="{ action: 'approve' }">
          <mat-icon>check_circle</mat-icon>
          Approve
        </button>
      }
    </mat-dialog-actions>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .dialog-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        padding: 20px 24px 0;
      }
      .dialog-header-title {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      h2[mat-dialog-title] {
        margin: 0;
        font-size: 18px;
        font-weight: 700;
        color: #0f172a;
      }
      .dialog-subtitle {
        font-size: 13px;
        color: #64748b;
        font-weight: 500;
      }
      .dialog-close {
        color: #94a3b8;
      }
      .dialog-content {
        padding: 16px 24px 24px;
      }
      .dialog-meta {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
        margin-bottom: 16px;
      }
      .meta-pill {
        display: inline-flex;
        align-items: center;
        padding: 5px 12px;
        border-radius: 9999px;
        background: #f1f5f9;
        color: #475569;
        font-size: 11px;
        font-weight: 600;
      }
      .ai-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 12px;
        border-radius: 8px;
        background: #f0fdfa;
        border: 1px solid #ccfbf1;
        color: #0d9488;
        font-size: 11px;
        font-weight: 700;

        mat-icon {
          font-size: 14px;
          width: 14px;
          height: 14px;
        }
      }
      .document-preview {
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 20px;
        background: #f8fafc;
        font-size: 13px;
        line-height: 1.6;
        color: #334155;
      }
      .document-preview h4 {
        margin: 0 0 16px;
        font-size: 15px;
        font-weight: 700;
        color: #0f172a;
      }
      .patient-summary {
        margin-bottom: 16px;
        padding-bottom: 16px;
        border-bottom: 1px dashed #cbd5e1;
      }
      .document-preview p {
        margin: 0 0 8px;
      }
      .document-preview strong {
        color: #0f172a;
      }
      .document-preview ul {
        margin: 0 0 14px;
        padding-left: 18px;
      }
      .document-preview li {
        margin-bottom: 6px;
      }
      .raw-content {
        white-space: pre-wrap;
        font-size: 11px;
      }
      .empty-output {
        color: #64748b;
        font-style: italic;
      }
      .rejection-panel {
        margin-top: 20px;
        padding: 16px;
        border-radius: 12px;
        background: #fff7ed;
        border: 1px solid #fed7aa;
      }
      .rejection-reason-field {
        width: 100%;
      }
      .dialog-actions {
        padding: 12px 24px 20px;
        gap: 10px;
      }
      .btn-primary {
        background: #2563eb;
        color: #fff;
      }
      .btn-reject {
        color: #dc2626;
        font-weight: 600;
      }
      .btn-approve {
        background: #16a34a;
        color: #fff;
        font-weight: 600;
      }
      .btn-approve mat-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
      }
    `,
  ],
})
export class DocumentApprovalDialogComponent {
  private readonly dialogRef = inject<MatDialogRef<DocumentApprovalDialogComponent>>(
    MatDialogRef,
  );
  readonly data: DocumentApprovalDialogData = inject(MAT_DIALOG_DATA);

  readonly doc = this.data.doc;
  rejectionReason = '';

  isViewMode(): boolean {
    return this.data.mode === 'view';
  }

  content(): any {
    const raw = this.doc.content;
    if (typeof raw === 'string') {
      try {
        return JSON.parse(raw);
      } catch {
        return null;
      }
    }
    return raw ?? null;
  }

  sections(): any {
    return this.content()?.['sections'] ?? {};
  }

  meds(): any[] {
    const c = this.content();
    if (!c) return [];
    return (
      c['medications'] ??
      this.sections()['medications_at_discharge'] ??
      this.sections()['active_medications'] ??
      this.sections()['medications_to_take'] ??
      []
    );
  }

  followUps(): any[] {
    return this.sections()['follow_up_instructions'] ?? [];
  }

  reconciliationSummary(): string {
    return this.sections()['reconciliation_summary'] ?? '';
  }

  sectionTitle(): string {
    const type = this.doc.document_type;
    const titles: Record<string, string> = {
      discharge_summary: 'Discharge Summary Draft',
      medication_reconciliation: 'Medication Reconciliation Report',
      follow_up_plan: 'Follow-up Care Plan',
      patient_instructions: 'Patient Instructions',
      transfer_summary: 'Transfer Summary',
      care_transition_summary: 'Care Transition Summary',
    };
    return titles[type] ?? 'Document Preview';
  }

  medLabel(med: any): string {
    const parts = [
      med['drug_name'],
      med['dose'],
      med['route'],
      med['frequency'],
    ].filter(Boolean);
    let label = parts.join(' ');
    const flags = med['flags'];
    if (Array.isArray(flags) && flags.length) {
      label += ` — ${flags.join(', ')}`;
    }
    const severity = med['severity'] || med['interaction_severity'];
    if (severity) {
      label += ` [${severity}]`;
    }
    return label || 'Unnamed medication';
  }

  trackMed(index: number, med: any): string {
    return (med['drug_name'] ?? '') + (med['dose'] ?? '');
  }
}
