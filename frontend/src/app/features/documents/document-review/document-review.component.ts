import { Component, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

interface DocumentField {
  label: string;
  aiText: string;
  editedText: string;
}

/**
 * DocumentReviewComponent — matches Hi-Fi wireframe SCR-006.
 */
@Component({
  selector: 'sh-document-review',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatIconModule],
  templateUrl: './document-review.component.html',
  styleUrl: './document-review.component.scss',
})
export class DocumentReviewComponent {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly patientName = signal<string>('Smith, John');
  readonly documentTitle = signal<string>('Discharge Summary');
  readonly aiGeneratedAt = signal<string>('14:32');
  readonly fallbackVisible = signal<boolean>(false);

  readonly fields = signal<DocumentField[]>([
    {
      label: 'Primary Diagnosis',
      aiText: 'Acute exacerbation of chronic heart failure (ICD-10: I50.23)',
      editedText: 'Acute on chronic systolic heart failure (ICD-10: I50.23)',
    },
    {
      label: 'Hospital Course',
      aiText: 'Patient admitted with dyspnea. Started on IV diuretics. Symptoms improved.',
      editedText: 'Patient admitted with dyspnea and weight gain. Started on IV diuretics with 2L net negative fluid balance. Symptoms improved. Weight target <85 kg discussed.',
    },
    {
      label: 'Discharge Medications',
      aiText: 'Furosemide 40 mg daily, Lisinopril 10 mg daily',
      editedText: 'Furosemide 40 mg daily, Lisinopril 10 mg daily, Metoprolol 25 mg BID',
    },
    {
      label: 'Follow-up Plan',
      aiText: 'Follow up with cardiology in 1 week.',
      editedText: 'Follow up with cardiology in 1 week. Primary care visit within 3-5 days.',
    },
  ]);

  readonly changeLog = signal<string>('Change log: 2 edits by Dr. David Chen — 14:37 | Field: Primary Diagnosis (ICD code updated) | Field: Hospital Course (weight target added)');

  constructor() {
    const documentId = this.route.snapshot.paramMap.get('id');
    // Static preview — no API call
  }

  goBack(): void {
    this.router.navigate(['/patients', 'enc-001']);
  }

  rejectDocument(): void {
    this.goBack();
  }

  saveDraft(): void {
    // Placeholder
  }

  approveDocument(): void {
    this.goBack();
  }

  showFallback(): void {
    this.fallbackVisible.set(true);
  }
}
