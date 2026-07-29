/**
 * LanguageSwitcherService — manages activeLanguage signal for discharge instructions.
 *
 * Isolated to its own injectable so it can be unit-tested independently of the
 * component (US-053 DoD: tested with Jasmine/Jest). The service reads the initial
 * language from the patient JWT preferred_language claim and exposes a writable
 * signal for the component to mutate.
 *
 * Design refs:
 *   US-053 Technical Notes  — Angular Signals preferred over BehaviorSubject
 *   US-053 AC Scenario 2    — client-side language switch; no API call; <500 ms
 *   design.md §4.1          — Angular 17 Signals; strict TypeScript
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../../core/auth/auth.service';
import {
  InstructionTranslations,
  SupportedLanguage,
} from './discharge-instructions.types';

@Injectable()
export class LanguageSwitcherService {
  private readonly auth = inject(AuthService);

  /** Currently selected display language. Defaults to JWT preferred_language or 'en'. */
  readonly activeLanguage = signal<SupportedLanguage>(
    this.auth.getPatientClaim<SupportedLanguage>('preferred_language') ?? 'en',
  );

  /** Loaded translations map set by the component after document fetch. */
  private readonly _translations = signal<InstructionTranslations | null>(null);

  /** Read-only translations accessor for computed signals. */
  readonly translations = this._translations.asReadonly();

  /**
   * Languages present in the loaded translations map.
   * Determines which toggle buttons to render.
   */
  readonly availableLanguages = computed<SupportedLanguage[]>(() => {
    const t = this._translations();
    if (!t) return ['en'];
    return Object.keys(t) as SupportedLanguage[];
  });

  /**
   * Resolved content for the active language.
   * Falls back to English if the preferred language key is absent.
   *
   * Angular re-evaluates this computed signal synchronously when
   * `activeLanguage` changes — ensuring the <500 ms requirement is met
   * (no async operations, no HTTP calls).
   */
  readonly currentContent = computed(() => {
    const t = this._translations();
    if (!t) return null;
    return t[this.activeLanguage()] ?? t['en'];
  });

  /** Loads translations into the service after the document HTTP call resolves. */
  setTranslations(translations: InstructionTranslations): void {
    this._translations.set(translations);
    // Ensure active language is supported by the loaded document;
    // fall back to 'en' silently if not available.
    const lang = this.activeLanguage();
    if (!translations[lang]) {
      this.activeLanguage.set('en');
    }
  }

  /**
   * Switch the active language.
   *
   * @param lang — must be a key present in availableLanguages()
   */
  switchLanguage(lang: SupportedLanguage): void {
    this.activeLanguage.set(lang);
  }
}
