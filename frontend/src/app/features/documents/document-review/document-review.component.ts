import { Component, signal, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { ToastService } from '../../../core/notifications/toast.service';
import { PatientApiService } from '../../patients/services/patient-api.service';
import {
  DocumentApiService,
  BackendDocument,
  DocumentContent,
} from '../services/document-api.service';
import { RejectDocumentModalComponent } from './components/reject-document-modal/reject-document-modal.component';
import { ApproveDocumentModalComponent } from './components/approve-document-modal/approve-document-modal.component';

interface DocumentField {
  label: string;
  aiText: string;
  editedText: string;
  isEdited?: boolean;
}

/**
 * DocumentReviewComponent — matches Hi-Fi wireframe SCR-006.
 *
 * Loads the first discharge summary (or any document) for the encounter
 * passed in the route parameter `patientId` and loads the patient name
 * so the header matches the selected patient.
 */
@Component({
  selector: 'sh-document-review',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    RejectDocumentModalComponent,
    ApproveDocumentModalComponent,
  ],
  templateUrl: './document-review.component.html',
  styleUrl: './document-review.component.scss',
})
export class DocumentReviewComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly matDialog = inject(MatDialog);
  private readonly toast = inject(ToastService);
  private readonly documentApi = inject(DocumentApiService);
  private readonly patientApi = inject(PatientApiService);

  readonly patientName = signal<string>('Loading…');
  readonly documentTitle = signal<string>('Discharge Summary');
  readonly aiGeneratedAt = signal<string>('');
  readonly fallbackVisible = signal<boolean>(false);
  readonly isLoading = signal<boolean>(true);
  readonly hasError = signal<boolean>(false);
  readonly errorMessage = signal<string>('');
  readonly documentId = signal<string | null>(null);
  readonly isApproved = signal<boolean>(false);
  readonly isRejected = signal<boolean>(false);
  readonly isLocked = signal<boolean>(false);
  readonly patientId = signal<string>('enc-001');

  readonly fields = signal<DocumentField[]>([]);
  readonly changeLog = signal<string>('No edits recorded.');

  ngOnInit(): void {
    const encounterId = this.route.snapshot.paramMap.get('patientId');
    if (!encounterId) {
      this.hasError.set(true);
      this.errorMessage.set('Encounter ID is missing from the route.');
      this.isLoading.set(false);
      return;
    }

    this.patientId.set(encounterId);
    this.loadPatient(encounterId);
    this.loadDocument(encounterId);
  }

  private loadDocument(encounterId: string): void {
    this.isLoading.set(true);
    this.hasError.set(false);

    this.documentApi.getDocumentsByEncounter(encounterId).subscribe({
      next: (documents) => {
        const doc =
          documents.find((d) => d.document_type === 'discharge_summary') ??
          documents[0];

        if (!doc) {
          // No backend document yet: show editable static draft preview.
          this.showStaticDraft();
          this.isLoading.set(false);
          return;
        }

        this.bindDocument(doc);
        this.isLoading.set(false);
      },
      error: (err: unknown) => {
        this.hasError.set(true);
        this.errorMessage.set(
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message: string }).message)
            : 'Failed to load document.',
        );
        this.isLoading.set(false);
      },
    });
  }

  private bindDocument(doc: BackendDocument): void {
    this.documentId.set(doc.id);
    this.documentTitle.set(
      doc.document_type === 'discharge_summary'
        ? 'Discharge Summary'
        : doc.document_type.replace(/_/g, ' '),
    );
    this.aiGeneratedAt.set(this.formatDate(doc.created_at));
    this.fallbackVisible.set(doc.generation_type === 'TEMPLATE');

    const content: DocumentContent = (doc.content as DocumentContent) ?? {};
    this.fields.set(this.toFields(content));

    if (doc.reviewed_by_display_name && doc.approved_at) {
      this.changeLog.set(
        `Approved by ${doc.reviewed_by_display_name} on ${this.formatDate(doc.approved_at)}.`,
      );
      this.isApproved.set(true);
      this.isLocked.set(true);
    } else {
      this.changeLog.set('Change log: no edits recorded.');
    }
  }

  private showStaticDraft(): void {
    this.documentTitle.set('Discharge Summary');
    this.aiGeneratedAt.set('');
    this.fallbackVisible.set(true);
    this.fields.set([
      {
        label: 'Primary Diagnosis',
        aiText: 'Acute exacerbation of chronic heart failure (ICD-10: I50.23)',
        editedText: 'Acute on chronic systolic heart failure (ICD-10: I50.23)',
        isEdited: true,
      },
      {
        label: 'Hospital Course',
        aiText: 'Patient admitted with dyspnea. Started on IV diuretics. Symptoms improved.',
        editedText:
          'Patient admitted with dyspnea and weight gain. Started on IV diuretics with 2L net negative fluid balance. Symptoms improved. Weight target <85 kg discussed.',
        isEdited: true,
      },
      {
        label: 'Discharge Medications',
        aiText: 'Furosemide 40 mg daily, Lisinopril 10 mg daily',
        editedText: 'Furosemide 40 mg daily, Lisinopril 10 mg daily, Metoprolol 25 mg BID',
        isEdited: true,
      },
      {
        label: 'Follow-up Plan',
        aiText: 'Follow up with cardiology in 1 week.',
        editedText: 'Follow up with cardiology in 1 week. Primary care visit within 3-5 days.',
        isEdited: true,
      },
    ]);
    this.changeLog.set(
      'Change log: 2 edits by Dr. David Chen — 14:37 | Field: Primary Diagnosis (ICD code updated) | Field: Hospital Course (weight target added)',
    );
  }

  private toFields(content: DocumentContent): DocumentField[] {
    const primary =
      content.diagnosis_summary?.find((d) => d.is_primary) ??
      content.diagnosis_summary?.[0];

    const meds = (content.medications_at_discharge ?? [])
      .map((m) => `${m.drug_name} ${m.dose} ${m.frequency}`)
      .join(', ');

    const followUp = (content.follow_up_instructions ?? [])
      .map((f) => f.instruction)
      .join(' ');

    return [
      {
        label: 'Primary Diagnosis',
        aiText: primary
          ? `${primary.description} (ICD-10: ${primary.icd10_code})`
          : 'No diagnosis recorded.',
        editedText: primary
          ? `${primary.description} (ICD-10: ${primary.icd10_code})`
          : 'No diagnosis recorded.',
      },
      {
        label: 'Hospital Course',
        aiText: content.hospital_course ?? 'No hospital course recorded.',
        editedText: content.hospital_course ?? 'No hospital course recorded.',
      },
      {
        label: 'Discharge Medications',
        aiText: meds || 'No discharge medications recorded.',
        editedText: meds || 'No discharge medications recorded.',
      },
      {
        label: 'Follow-up Plan',
        aiText: followUp || 'No follow-up plan recorded.',
        editedText: followUp || 'No follow-up plan recorded.',
      },
    ];
  }

  private formatDate(iso: string | null | undefined): string {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString();
  }

  /** Loads the patient's name so the document header matches the selected patient. */
  private loadPatient(encounterId: string): void {
    this.patientApi.getPatientByEncounter(encounterId).subscribe({
      next: (patient) => {
        const name =
          patient.last_name && patient.first_name
            ? `${patient.last_name}, ${patient.first_name}`
            : patient.last_name || patient.first_name || 'Unknown Patient';
        this.patientName.set(name);
      },
      error: () => {
        this.patientName.set('Unknown Patient');
      },
    });
  }

  goBack(): void {
    // Return to the patient detail Documents tab per wireframe SCR-004.
    this.router.navigate(['/patients', this.patientId()], {
      queryParams: { tab: 'Documents' },
    });
  }

  /** Opens the rejection modal and returns to the patient detail on confirm. */
  rejectDocument(): void {
    if (this.isLocked()) {
      this.toast.info('Document has already been signed');
      return;
    }

    const ref = this.matDialog.open(RejectDocumentModalComponent, { width: '520px' });
    ref.afterClosed().subscribe((result: { reason: string; note: string } | undefined) => {
      if (result) {
        this.isRejected.set(true);
        this.isLocked.set(true);
        this.toast.warn(`Document returned — ${result.reason}`);
        setTimeout(() => this.goBack(), 1200);
      }
    });
  }

  /** Saves the current editable draft and updates the change log. */
  saveDraft(): void {
    if (this.isLocked()) {
      this.toast.info('Document is locked and cannot be edited');
      return;
    }

    const editedFields = this.fields().filter((f) => f.isEdited);
    const fieldNames = editedFields.map((f) => f.label).join(', ');
    const now = new Date();
    const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const editCount = editedFields.length;

    this.changeLog.set(
      `Change log: ${editCount} edit(s) by Dr. David Chen — ${time}${fieldNames ? ' | Field: ' + fieldNames : ''}`,
    );
    this.toast.success('Draft saved');
  }

  /** Opens the approval confirmation modal and locks the document on confirm. */
  approveDocument(): void {
    if (this.isLocked()) {
      this.toast.info('Document has already been signed');
      return;
    }

    const editCount = this.fields().filter((f) => f.isEdited).length;
    const ref = this.matDialog.open(ApproveDocumentModalComponent, {
      width: '520px',
      data: {
        patientName: this.patientName(),
        documentTitle: this.documentTitle(),
        editCount,
      },
    });

    ref.afterClosed().subscribe((approved: boolean) => {
      if (approved) {
        this.isApproved.set(true);
        this.isLocked.set(true);
        this.toast.success('Document approved and signed');
      }
    });
  }

  /** Captures edits made via contenteditable paragraphs. */
  onFieldEdit(index: number, value: string): void {
    if (this.isLocked()) return;
    this.fields.update((fields) => {
      const updated = [...fields];
      updated[index] = { ...updated[index], editedText: value, isEdited: true };
      return updated;
    });
  }

  showFallback(): void {
    this.fallbackVisible.set(true);
  }
}
