/**
 * Unit tests for DischargeInstructionsComponent (US-053 TASK-002).
 *
 * Covers: component initialization, language switching, section rendering,
 * loading/error states, and axe-core accessibility scan.
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { axe, toHaveNoViolations } from 'jasmine-axe';
import { DischargeInstructionsComponent } from './discharge-instructions.component';
import { AuthService } from '../../../core/auth/auth.service';
import { environment } from '../../../../environments/environment';
import { InstructionTranslations } from './discharge-instructions.types';

expect.extend(toHaveNoViolations);

const MOCK_TRANSLATIONS: InstructionTranslations = {
  en: {
    medications: [
      { name: 'Lisinopril', dosage: '10 mg', frequency: 'once daily' },
      { name: 'Aspirin', dosage: '81 mg', frequency: 'once daily', notes: 'take with food' },
    ],
    activity: 'Gradually increase walking. No heavy lifting for 6 weeks.',
    diet: 'Low-sodium diet. Limit fluid to 2 liters per day.',
    follow_up: [
      { provider: 'Cardiology', timeframe: 'within 2 weeks', contact: '(555) 123-4567' },
    ],
    warning_signs: ['Chest pain at rest', 'Severe shortness of breath', 'Syncope'],
  },
  fr: {
    medications: [
      { name: 'Lisinopril', dosage: '10 mg', frequency: 'une fois par jour' },
      { name: 'Aspirine', dosage: '81 mg', frequency: 'une fois par jour', notes: 'prendre avec de la nourriture' },
    ],
    activity: 'Augmentez progressivement vos marches. Pas de levage lourd pendant 6 semaines.',
    diet: 'Régime hyposodé. Limitez les liquides à 2 litres par jour.',
    follow_up: [
      { provider: 'Cardiologie', timeframe: 'dans les 2 semaines', contact: '(555) 123-4567' },
    ],
    warning_signs: ['Douleur thoracique au repos', 'Essoufflement grave', 'Syncope'],
  },
};

describe('DischargeInstructionsComponent', () => {
  let component: DischargeInstructionsComponent;
  let fixture: ComponentFixture<DischargeInstructionsComponent>;
  let httpMock: HttpTestingController;
  let authSpy: jasmine.SpyObj<AuthService>;

  beforeEach(async () => {
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['getPatientClaim']);
    authSpy.getPatientClaim.and.returnValue('fr');

    await TestBed.configureTestingModule({
      imports: [DischargeInstructionsComponent, HttpClientTestingModule],
      providers: [
        { provide: AuthService, useValue: authSpy },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: {
                get: (key: string) => (key === 'encounterId' ? 'ENC-123' : null),
              },
            },
          },
        },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(DischargeInstructionsComponent);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create the component', () => {
    expect(component).toBeTruthy();
  });

  it('should initialise activeLanguage from JWT preferred_language=fr', () => {
    fixture.detectChanges();
    expect(component['activeLanguage']()).toBe('fr');
  });

  it('should display loading spinner on init', () => {
    fixture.detectChanges();
    const spinner = fixture.nativeElement.querySelector('mat-spinner');
    expect(spinner).toBeTruthy();
  });

  it('should fetch discharge document and load French content', (done) => {
    fixture.detectChanges();

    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    expect(req.request.method).toBe('GET');
    req.flush({ id: 'DOC-1', encounter_id: 'ENC-123', translations: MOCK_TRANSLATIONS });

    setTimeout(() => {
      fixture.detectChanges();
      expect(component['isLoading']()).toBe(false);
      expect(component['currentContent']()?.activity).toContain('marches');
      done();
    }, 0);
  });

  it('should render all five sections with correct icons', (done) => {
    fixture.detectChanges();
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    req.flush({ id: 'DOC-1', encounter_id: 'ENC-123', translations: MOCK_TRANSLATIONS });

    setTimeout(() => {
      fixture.detectChanges();
      const sections = fixture.nativeElement.querySelectorAll('.instruction-section');
      expect(sections.length).toBe(5);

      // Check for section icons
      const icons = fixture.nativeElement.querySelectorAll('mat-icon');
      const iconTexts = Array.from(icons).map((icon: any) => icon.textContent.trim());
      expect(iconTexts).toContain('medication');
      expect(iconTexts).toContain('directions_walk');
      done();
    }, 0);
  });

  it('should switch language from FR to EN without new HTTP call', (done) => {
    fixture.detectChanges();
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    req.flush({ id: 'DOC-1', encounter_id: 'ENC-123', translations: MOCK_TRANSLATIONS });

    setTimeout(() => {
      fixture.detectChanges();
      component['onLanguageChange']('en');
      fixture.detectChanges();

      expect(component['activeLanguage']()).toBe('en');
      expect(component['currentContent']()?.activity).toContain('walking');

      // Verify no second HTTP request
      httpMock.expectNone(
        `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
      );
      done();
    }, 0);
  });

  it('should display error message on HTTP failure', (done) => {
    fixture.detectChanges();
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    req.error(new ErrorEvent('Network error'));

    setTimeout(() => {
      fixture.detectChanges();
      expect(component['isLoading']()).toBe(false);
      expect(component['errorMessage']()).toContain('Unable to load');

      const errorBanner = fixture.nativeElement.querySelector('.error-banner');
      expect(errorBanner).toBeTruthy();
      done();
    }, 0);
  });

  it('should apply warning-section directive to warning signs section', (done) => {
    fixture.detectChanges();
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    req.flush({ id: 'DOC-1', encounter_id: 'ENC-123', translations: MOCK_TRANSLATIONS });

    setTimeout(() => {
      fixture.detectChanges();
      const warningSections = fixture.nativeElement.querySelectorAll('[appWarningSection]');
      expect(warningSections.length).toBe(1);
      expect(warningSections[0]).toHaveClass('warning-section');
      done();
    }, 0);
  });

  it('should render language switcher buttons for available languages', (done) => {
    fixture.detectChanges();
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    req.flush({ id: 'DOC-1', encounter_id: 'ENC-123', translations: MOCK_TRANSLATIONS });

    setTimeout(() => {
      fixture.detectChanges();
      const toggles = fixture.nativeElement.querySelectorAll('mat-button-toggle');
      expect(toggles.length).toBe(2); // EN and FR
      done();
    }, 0);
  });

  it('should have zero axe-core WCAG 2.1 AA violations', async () => {
    fixture.detectChanges();
    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/api/v1/documents/ENC-123/discharge`
    );
    req.flush({ id: 'DOC-1', encounter_id: 'ENC-123', translations: MOCK_TRANSLATIONS });

    await new Promise((resolve) => setTimeout(resolve, 100));
    fixture.detectChanges();

    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });
});
