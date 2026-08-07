import { Component, signal, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { DocumentApiService, BackendDocument, DocumentContent } from '../services/document-api.service';

interface DocumentField {
  label: string;
  aiText: string;
  editedText: string;
}

/**
 * DocumentReviewComponent — matches Hi-Fi wireframe SCR-006.
 *
 * Loads the first discharge summary (or any document) for the encounter
 * passed in the route parameter `patientId`.
 */
@Component({
  selector: 'sh-document-review',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule],
  templateUrl: './document-review.component.html',
  styleUrl: './document-review.component.scss',
})
export class DocumentReviewComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly documentApi = inject(DocumentApiService);

  readonly patientName = signal<string>('');
  readonly documentTitle = signal<string>('Discharge Summary');
  readonly aiGeneratedAt = signal<string>('');
  readonly fallbackVisible = signal<boolean>(false);
  readonly isLoading = signal<boolean>(true);
  readonly hasError = signal<boolean>(false);
  readonly errorMessage = signal<string>('');
  readonly documentId = signal<string | null>(null);

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
          this.hasError.set(true);
          this.errorMessage.set('No documents found for this encounter.');
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
            : 'Failed to load document.'
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
        : doc.document_type.replace(/_/g, ' ')
    );
    this.aiGeneratedAt.set(this.formatDate(doc.created_at));
    this.fallbackVisible.set(doc.generation_type === 'TEMPLATE');

    const content: DocumentContent = doc.content ?? {};
    this.fields.set(this.toFields(content));

    if (doc.reviewed_by_display_name && doc.approved_at) {
      this.changeLog.set(
        `Approved by ${doc.reviewed_by_display_name} on ${this.formatDate(doc.approved_at)}.`
      );
    } else {
      this.changeLog.set('Change log: no edits recorded.');
    }
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

  goBack(): void {
    const encounterId = this.route.snapshot.paramMap.get('patientId');
    this.router.navigate(['/patients', encounterId ?? '']);
  }

  rejectDocument(): void {
    this.goBack();
  }

  saveDraft(): void {
    // Placeholder — wire PATCH /api/v1/documents/{id} when save-draft schema is ready
  }

  approveDocument(): void {
    // Placeholder — wire PATCH /api/v1/documents/{id}/approve when approval flow is ready
    this.goBack();
  }

  showFallback(): void {
    this.fallbackVisible.set(true);
  }
}
