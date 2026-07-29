/**
 * Unit tests for LanguageSwitcherService (US-053 TASK-003).
 *
 * Covers: signal initialisation, switchLanguage, currentContent fallback,
 * setTranslations with unsupported active language.
 */
import { TestBed } from '@angular/core/testing';
import { LanguageSwitcherService } from './language-switcher.service';
import { AuthService } from '../../../core/auth/auth.service';
import { InstructionTranslations } from './discharge-instructions.types';

const MOCK_TRANSLATIONS: InstructionTranslations = {
  en: {
    medications: [{ name: 'Metoprolol', dosage: '25 mg', frequency: 'twice daily' }],
    activity: 'No heavy lifting for 4 weeks.',
    diet: 'Low-sodium diet.',
    follow_up: [{ provider: 'Cardiologist', timeframe: 'within 7 days' }],
    warning_signs: ['Chest pain', 'Shortness of breath'],
  },
  fr: {
    medications: [{ name: 'Métoprolol', dosage: '25 mg', frequency: 'deux fois par jour' }],
    activity: 'Aucun port de charges lourdes pendant 4 semaines.',
    diet: 'Régime pauvre en sodium.',
    follow_up: [{ provider: 'Cardiologue', timeframe: 'dans les 7 jours' }],
    warning_signs: ['Douleur thoracique', 'Essoufflement'],
  },
};

describe('LanguageSwitcherService', () => {
  let service: LanguageSwitcherService;
  let authSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['getPatientClaim']);
    authSpy.getPatientClaim.and.returnValue('fr'); // Simulate preferred_language=fr JWT claim

    TestBed.configureTestingModule({
      providers: [
        LanguageSwitcherService,
        { provide: AuthService, useValue: authSpy },
      ],
    });

    service = TestBed.inject(LanguageSwitcherService);
    service.setTranslations(MOCK_TRANSLATIONS);
  });

  it('should initialise activeLanguage from JWT preferred_language claim', () => {
    expect(service.activeLanguage()).toBe('fr');
  });

  it('should resolve currentContent in the active language', () => {
    const content = service.currentContent();
    expect(content?.activity).toBe('Aucun port de charges lourdes pendant 4 semaines.');
  });

  it('should switch language synchronously and update currentContent', () => {
    service.switchLanguage('en');
    expect(service.activeLanguage()).toBe('en');
    expect(service.currentContent()?.activity).toBe('No heavy lifting for 4 weeks.');
  });

  it('should fall back to English if active language is not in translations', () => {
    // Load translations that do not include 'es'
    const enOnly: InstructionTranslations = { en: MOCK_TRANSLATIONS.en };
    service.switchLanguage('es');
    service.setTranslations(enOnly);
    // setTranslations corrects to 'en' when current lang is not available
    expect(service.activeLanguage()).toBe('en');
    expect(service.currentContent()?.activity).toBe('No heavy lifting for 4 weeks.');
  });

  it('should list available languages from loaded translations', () => {
    const langs = service.availableLanguages();
    expect(langs).toContain('en');
    expect(langs).toContain('fr');
    expect(langs.length).toBe(2);
  });
});
