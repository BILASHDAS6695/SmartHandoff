import {
  Component, OnInit, ChangeDetectionStrategy, signal, inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatListModule } from '@angular/material/list';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDividerModule } from '@angular/material/divider';
import { DocumentApiService } from '../../services/document-api.service';
import { PendingDocument } from '../../models/pending-document.model';
import { DocumentQueueStore } from '../../store/document-queue.store';

/**
 * Displays the physician's document approval queue on the dashboard.
 * Lists PENDING_REVIEW AI-generated documents with approve/reject actions.
 *
 * Intended placement: dashboard home panel (physician role only).
 * Queue count is also exposed via DocumentQueueStore for sidebar badge.
 */
@Component({
  selector: 'app-document-queue',
  standalone: true,
  imports: [
    CommonModule,
    MatListModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatDividerModule,
  ],
  templateUrl: './document-queue.component.html',
  styleUrls: ['./document-queue.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DocumentQueueComponent implements OnInit {
  private readonly documentApi = inject(DocumentApiService);
  private readonly queueStore = inject(DocumentQueueStore);

  documents = signal<PendingDocument[]>([]);
  isLoading = signal(true);
  hasError = signal(false);
  /** Track which documentId is being actioned to show per-item spinner */
  pendingActionId = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading.set(true);
    this.hasError.set(false);
    this.documentApi.getPendingReviewQueue().subscribe({
      next: (docs) => {
        this.documents.set(docs);
        this.queueStore.setCount(docs.length);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  approve(doc: PendingDocument): void {
    this.pendingActionId.set(doc.documentId);
    this.documentApi
      .reviewDocument(doc.documentId, { action: 'APPROVED' })
      .subscribe({
        next: () => this.removeDocument(doc.documentId),
        error: () => this.pendingActionId.set(null),
      });
  }

  reject(doc: PendingDocument): void {
    this.pendingActionId.set(doc.documentId);
    // Rejection reason collection can be extended via a prompt dialog in a later sprint
    this.documentApi
      .reviewDocument(doc.documentId, { action: 'REJECTED' })
      .subscribe({
        next: () => this.removeDocument(doc.documentId),
        error: () => this.pendingActionId.set(null),
      });
  }

  private removeDocument(documentId: string): void {
    this.documents.update((docs) => docs.filter((d) => d.documentId !== documentId));
    this.queueStore.setCount(this.documents().length);
    this.pendingActionId.set(null);
  }

  trackById(index: number, doc: PendingDocument): string {
    return doc.documentId;
  }
}
