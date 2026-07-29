/**
 * DischargeInstructionsComponent — structured discharge instructions (US-053, US-054).
 *
 * Displays five instruction sections (medications, activity, diet, follow-up,
 * warning signs) with Angular Material icons. Language is driven by the
 * `activeLanguage` signal initialised from the patient's JWT preferred_language
 * claim. All content derives from a `computed` signal for zero-overhead re-renders.
 *
 * US-054 Integration: Provides PDF download and PWA install buttons.
 *   - downloadPdf() — generates PDF via PdfDownloadService with HIPAA-compliant PHI
 *   - installApp() — triggers PWA installation via PwaInstallPromptService
 *
 * Design refs:
 *   US-053 Technical Notes  — activeLanguage signal; computed currentContent
 *   US-053 DoD              — DischargeInstructionsComponent; mat-icon healthcare icons
 *   US-053 AC Scenario 1    — preferred_language=fr renders French on load
 *   US-054 TASK-001         — PDF download with jsPDF, HIPAA PHI scoping
 *   US-054 TASK-004         — PWA install prompt service integration
 *   design.md §3.4          — patient-portal lazy-loaded feature module
 *   design.md §4.1          — Angular 17; Angular Material 17; strict TypeScript
 *   NFR-001                 — <2 s initial load; lazy component; minimal HTTP calls
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatDividerModule } from '@angular/material/divider';
import { MatButtonModule } from '@angular/material/button';

import { AuthService } from '../../../core/auth/auth.service';
import { PdfDownloadService } from './pdf-download.service';
import { PwaInstallPromptService } from '../../../core/pwa/pwa-install-prompt.service';
import { environment } from '../../../../environments/environment';
import {
  INSTRUCTION_SECTIONS,
  LANGUAGE_LABELS,
  InstructionTranslations,
  SupportedLanguage,
} from './discharge-instructions.types';
import { WarningSectionDirective } from './warning-section.directive';
import { OfflineBannerComponent } from '../offline-banner/offline-banner.component';
import { ChatbotWidgetComponent } from '../components/chatbot-widget/chatbot-widget.component';
import { AppointmentSummaryComponent } from '../components/appointment-summary/appointment-summary.component';

interface DocumentResponse {
  id: string;
  encounter_id: string;
  translations: InstructionTranslations;
}

@Component({
  selector: 'app-discharge-instructions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatButtonToggleModule,
    MatButtonModule,
    MatCardModule,
    MatDividerModule,
    WarningSectionDirective,
    OfflineBannerComponent,
    ChatbotWidgetComponent,
    AppointmentSummaryComponent,
  ],
  templateUrl: './discharge-instructions.component.html',
  styleUrl: './discharge-instructions.component.scss',
})
export class DischargeInstructionsComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly pdfService = inject(PdfDownloadService);
  private readonly pwaInstallPromptService = inject(PwaInstallPromptService);

  /** Public accessor for PWA canInstall signal for template. */
  protected readonly canInstallPwa = computed(() => this.pwaInstallPromptService.canInstall());

  /** Section metadata (icon + label) used to drive *ngFor in template. */
  protected readonly sections = INSTRUCTION_SECTIONS;

  /** Language labels for MatButtonToggle display. */
  protected readonly languageLabels = LANGUAGE_LABELS;

  /** Currently active language for display. Initialised from JWT preferred_language. */
  protected readonly activeLanguage = signal<SupportedLanguage>('en');

  /** Loaded translations map; null until the HTTP response arrives. */
  private readonly translations = signal<InstructionTranslations | null>(null);

  /** Patient first name from JWT claim (HIPAA-compliant PHI for PDF). */
  private readonly patientFirstName = signal<string>('Patient');

  /** Hospital name from JWT claim (HIPAA-compliant PHI for PDF). */
  private readonly hospitalName = signal<string>('Hospital');

  /** Discharge date for PDF header; initialised from route param or current date. */
  private readonly dischargeDate = signal<string>(new Date().toISOString().split('T')[0]);

  /** Available languages derived from loaded translations keys. */
  protected readonly availableLanguages = computed<SupportedLanguage[]>(() => {
    const t = this.translations();
    if (!t) return ['en'];
    return Object.keys(t) as SupportedLanguage[];
  });

  /**
   * Active language content resolved from translations.
   * Falls back to English if the preferred language is not available.
   */
  protected readonly currentContent = computed(() => {
    const t = this.translations();
    if (!t) return null;
    return t[this.activeLanguage()] ?? t['en'];
  });

  /** True while the document HTTP request is in flight. */
  protected readonly isLoading = signal(true);

  /** Non-null when the document fetch fails. */
  protected readonly errorMessage = signal<string | null>(null);

  ngOnInit(): void {
    // Seed active language from patient JWT claim before HTTP call resolves
    const preferredLang = this.auth.getPatientClaim<SupportedLanguage>('preferred_language');
    if (preferredLang) {
      this.activeLanguage.set(preferredLang);
    }

    // Extract patient metadata from JWT claims for HIPAA-compliant PDF generation
    const firstName = this.auth.getPatientClaim<string>('given_name') || 'Patient';
    const hospital = this.auth.getPatientClaim<string>('hospital_name') || 'Hospital';
    this.patientFirstName.set(firstName);
    this.hospitalName.set(hospital);

    const encounterId = this.route.snapshot.paramMap.get('encounterId') ?? '';
    this.http
      .get<DocumentResponse>(
        `${environment.apiBaseUrl}/api/v1/documents/${encounterId}/discharge`,
      )
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (doc) => {
          this.translations.set(doc.translations);
          this.isLoading.set(false);
        },
        error: () => {
          this.errorMessage.set('Unable to load your discharge instructions. Please try again.');
          this.isLoading.set(false);
        },
      });
  }

  /** Called by MatButtonToggle change event to switch language. */
  protected onLanguageChange(lang: SupportedLanguage): void {
    this.activeLanguage.set(lang);
  }

  /**
   * Generate and download PDF of discharge instructions.
   * Uses PdfDownloadService with HIPAA-compliant PHI scoping (firstName, dischargeDate, hospitalName only).
   * Triggered by PDF download button click (US-054 TASK-001).
   */
  protected downloadPdf(): void {
    const content = this.currentContent();
    if (!content) {
      console.warn('Cannot download PDF: instructions not yet loaded');
      return;
    }

    this.pdfService.download({
      firstName: this.patientFirstName(),
      dischargeDate: this.dischargeDate(),
      hospitalName: this.hospitalName(),
      content,
    });
  }

  /**
   * Trigger PWA installation prompt.
   * Shows browser's native installation UI (Add to Home Screen).
   * Only callable when canInstallPwa signal is true.
   * Triggered by PWA install button click (US-054 TASK-004).
   */
  protected installApp(): void {
    this.pwaInstallPromptService.prompt();
  }
}
