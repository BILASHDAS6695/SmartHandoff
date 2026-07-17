---
id: TASK-004
title: "Unit Tests — Chatbot Scope Enforcement, Urgency Banner Rendering & .ics Download"
user_story: US-055
epic: EP-010
sprint: 2
layer: Testing
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-055/TASK-001, US-055/TASK-002, US-055/TASK-003]
---

# TASK-004: Unit Tests — Chatbot Scope Enforcement, Urgency Banner Rendering & .ics Download

> **Story:** US-055 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-055 DoD requires unit tests covering three specific areas:

1. **Chatbot widget scope enforcement** — when `ChatbotService` returns a scope-refusal response, the widget renders the message without suppression or alteration
2. **Urgency response rendering** — when `urgency=true` is returned, the widget renders the full-width red banner with an `<a href="tel:911">` link
3. **.ics download** — `generateIcsContent()` produces a valid `BEGIN:VCALENDAR` string with correct `DTSTART` and `SUMMARY` fields; `downloadIcsFile()` triggers a Blob download

**Test framework:** Angular `TestBed` with `jasmine` / `karma` (project standard per ADR-005 Angular 17).

**Test files to create:**

| Test File | Component / Utility Under Test |
|-----------|-------------------------------|
| `chatbot-widget.component.spec.ts` | `ChatbotWidgetComponent` — scope enforcement, urgency banner |
| `ics-generator.spec.ts` | `generateIcsContent()`, `downloadIcsFile()` |

**Mocking strategy:**

| Dependency | Mock Approach |
|------------|--------------|
| `ChatbotService.sendMessage()` | `jasmine.createSpyObj` returning `of(ChatResponse)` |
| `PatientAuthService.getEncounterId()` | `jasmine.createSpyObj` returning `'ENC-001'` |
| `PatientAuthService.getPatientId()` | `jasmine.createSpyObj` returning `'PAT-001'` |
| `URL.createObjectURL` | `spyOn(URL, 'createObjectURL').and.returnValue('blob:mock')` |
| `URL.revokeObjectURL` | `spyOn(URL, 'revokeObjectURL')` |
| `HTMLAnchorElement.click` | Spy on `anchor.click` via `spyOn` |

---

## Acceptance Criteria Addressed

| AC Scenario | Test Cases |
|-------------|-----------|
| Scenario 3 | `renders_scope_refusal_message_without_alteration` |
| Scenario 4 | `renders_urgency_banner_when_urgency_true`, `urgency_banner_contains_tel_911_link` |
| DoD (.ics) | `generates_valid_vcalendar_string`, `ics_dtstart_format_is_correct`, `ics_summary_is_smarthandoff`, `download_creates_blob_and_triggers_click` |

---

## Implementation Steps

### 1. Scaffold test files

```bash
touch frontend/src/app/features/patient-portal/components/chatbot-widget/chatbot-widget.component.spec.ts
touch frontend/src/app/features/patient-portal/utils/ics-generator.spec.ts
```

### 2. Implement `chatbot-widget.component.spec.ts`

```typescript
/**
 * Unit tests for ChatbotWidgetComponent.
 *
 * Coverage:
 *   US-055 AC Scenario 3 — scope-refusal message rendered without client-side filtering
 *   US-055 AC Scenario 4 — urgency=true → red banner with <a href="tel:911"> link
 */
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { of, throwError } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ChatbotWidgetComponent } from './chatbot-widget.component';
import { ChatbotService } from '../../services/chatbot.service';
import { PatientAuthService } from '../../../auth/services/patient-auth.service';
import { ChatResponse } from '../../models/chat.model';

describe('ChatbotWidgetComponent', () => {
  let fixture: ComponentFixture<ChatbotWidgetComponent>;
  let component: ChatbotWidgetComponent;
  let chatbotServiceSpy: jasmine.SpyObj<ChatbotService>;
  let patientAuthSpy: jasmine.SpyObj<PatientAuthService>;

  beforeEach(async () => {
    chatbotServiceSpy = jasmine.createSpyObj<ChatbotService>('ChatbotService', ['sendMessage']);
    patientAuthSpy = jasmine.createSpyObj<PatientAuthService>('PatientAuthService', [
      'getEncounterId',
      'getPatientId',
    ]);
    patientAuthSpy.getEncounterId.and.returnValue('ENC-001');

    await TestBed.configureTestingModule({
      imports: [ChatbotWidgetComponent, NoopAnimationsModule],
      providers: [
        { provide: ChatbotService, useValue: chatbotServiceSpy },
        { provide: PatientAuthService, useValue: patientAuthSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatbotWidgetComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  // -----------------------------------------------------------------------
  // Panel open/close
  // -----------------------------------------------------------------------
  it('should start with the panel collapsed', () => {
    const panel = fixture.debugElement.query(By.css('.chatbot-panel'));
    expect(panel).toBeNull();
  });

  it('should expand the panel when toggle() is called', () => {
    component.toggle();
    fixture.detectChanges();
    const panel = fixture.debugElement.query(By.css('.chatbot-panel'));
    expect(panel).not.toBeNull();
  });

  // -----------------------------------------------------------------------
  // AC Scenario 3 — scope-refusal message rendered without alteration
  // -----------------------------------------------------------------------
  describe('Scope enforcement — AC Scenario 3', () => {
    const scopeRefusalMessage =
      'I can only answer questions about your own discharge instructions. ' +
      'For questions about other patients, please contact the care team.';

    beforeEach(() => {
      const response: ChatResponse = { message: scopeRefusalMessage, urgency: false };
      chatbotServiceSpy.sendMessage.and.returnValue(of(response));
      component.toggle();
      fixture.detectChanges();
    });

    it('renders the scope-refusal message as a standard assistant message', fakeAsync(() => {
      component.messageControl.setValue('What medications is John on?');
      component.sendMessage();
      tick();
      fixture.detectChanges();

      const assistantMessages = fixture.debugElement.queryAll(By.css('.message--assistant'));
      const lastMessage = assistantMessages[assistantMessages.length - 1];
      expect(lastMessage.nativeElement.textContent).toContain(
        'I can only answer questions about your own discharge instructions'
      );
    }));

    it('does NOT render an urgency banner for a scope-refusal response', fakeAsync(() => {
      component.messageControl.setValue('What medications is John on?');
      component.sendMessage();
      tick();
      fixture.detectChanges();

      const urgencyBanner = fixture.debugElement.query(By.css('.urgency-banner'));
      expect(urgencyBanner).toBeNull();
    }));
  });

  // -----------------------------------------------------------------------
  // AC Scenario 4 — urgency=true → full-width red banner with tel:911 link
  // -----------------------------------------------------------------------
  describe('Urgency response rendering — AC Scenario 4', () => {
    beforeEach(() => {
      const response: ChatResponse = {
        message: 'This sounds like a medical emergency. Please call 911 immediately.',
        urgency: true,
      };
      chatbotServiceSpy.sendMessage.and.returnValue(of(response));
      component.toggle();
      fixture.detectChanges();
    });

    it('renders the urgency banner when urgency=true', fakeAsync(() => {
      component.messageControl.setValue('I have severe chest pain');
      component.sendMessage();
      tick();
      fixture.detectChanges();

      const urgencyBanner = fixture.debugElement.query(By.css('.urgency-banner'));
      expect(urgencyBanner).not.toBeNull();
    }));

    it('urgency banner contains an <a href="tel:911"> link', fakeAsync(() => {
      component.messageControl.setValue('I have severe chest pain');
      component.sendMessage();
      tick();
      fixture.detectChanges();

      const callLink = fixture.debugElement.query(By.css('a[href="tel:911"]'));
      expect(callLink).not.toBeNull();
    }));

    it('urgency banner has role="alert" for screen reader announcement', fakeAsync(() => {
      component.messageControl.setValue('I have severe chest pain');
      component.sendMessage();
      tick();
      fixture.detectChanges();

      const banner = fixture.debugElement.query(By.css('.urgency-banner'));
      expect(banner.attributes['role']).toBe('alert');
    }));

    it('does NOT render urgency banner for a non-urgency response', fakeAsync(() => {
      const normalResponse: ChatResponse = {
        message: 'Take your medication with water.',
        urgency: false,
      };
      chatbotServiceSpy.sendMessage.and.returnValue(of(normalResponse));

      component.messageControl.setValue('How do I take my medication?');
      component.sendMessage();
      tick();
      fixture.detectChanges();

      const urgencyBanner = fixture.debugElement.query(By.css('.urgency-banner'));
      expect(urgencyBanner).toBeNull();
    }));
  });

  // -----------------------------------------------------------------------
  // Typing indicator
  // -----------------------------------------------------------------------
  it('shows typing indicator while request is in-flight', fakeAsync(() => {
    // Return a response after a tick to simulate async
    chatbotServiceSpy.sendMessage.and.returnValue(
      new (require('rxjs').Observable)((subscriber: any) => {
        setTimeout(() => {
          subscriber.next({ message: 'Hello', urgency: false });
          subscriber.complete();
        }, 100);
      })
    );

    component.toggle();
    fixture.detectChanges();
    component.messageControl.setValue('Hello');
    component.sendMessage();
    fixture.detectChanges();

    const typingIndicator = fixture.debugElement.query(By.css('.message--typing'));
    expect(typingIndicator).not.toBeNull();

    tick(100);
    fixture.detectChanges();
    const afterTypingIndicator = fixture.debugElement.query(By.css('.message--typing'));
    expect(afterTypingIndicator).toBeNull();
  }));

  // -----------------------------------------------------------------------
  // Error handling
  // -----------------------------------------------------------------------
  it('renders a fallback error message when the API fails', fakeAsync(() => {
    chatbotServiceSpy.sendMessage.and.returnValue(throwError(() => new Error('Network error')));

    component.toggle();
    fixture.detectChanges();
    component.messageControl.setValue('Hello');
    component.sendMessage();
    tick();
    fixture.detectChanges();

    const assistantMessages = fixture.debugElement.queryAll(By.css('.message--assistant'));
    const lastMessage = assistantMessages[assistantMessages.length - 1];
    expect(lastMessage.nativeElement.textContent).toContain('unable to respond right now');
  }));
});
```

### 3. Implement `ics-generator.spec.ts`

```typescript
/**
 * Unit tests for ics-generator utilities.
 *
 * Coverage:
 *   US-055 DoD — .ics: BEGIN:VCALENDAR format with DTSTART:YYYYMMDDTHHMMSSZ
 *   US-055 DoD — SUMMARY:SmartHandoff Follow-up Appointment
 *   US-055 DoD — .ics download triggers Blob + anchor click
 */
import { generateIcsContent, downloadIcsFile } from './ics-generator';
import { Appointment } from '../models/appointment.model';

describe('generateIcsContent', () => {
  const mockAppointment: Appointment = {
    id: 'appt-123',
    type: 'Follow-up with your doctor',
    date: '2026-07-28',
    time: '10:30:00',
    provider: 'Dr. Smith',
    location: 'Cardiology Clinic, Floor 3',
  };

  it('should produce a string starting with BEGIN:VCALENDAR', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics.startsWith('BEGIN:VCALENDAR')).toBeTrue();
  });

  it('should end with END:VCALENDAR', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics.trim().endsWith('END:VCALENDAR')).toBeTrue();
  });

  it('should contain SUMMARY:SmartHandoff Follow-up Appointment', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics).toContain('SUMMARY:SmartHandoff Follow-up Appointment');
  });

  it('should contain DTSTART in YYYYMMDDTHHMMSSZ format for a timed appointment', () => {
    const ics = generateIcsContent(mockAppointment);
    // Expected: DTSTART:20260728T103000Z
    expect(ics).toContain('DTSTART:20260728T103000Z');
  });

  it('should default DTSTART to T090000Z when time is null', () => {
    const apptNoTime: Appointment = { ...mockAppointment, time: null };
    const ics = generateIcsContent(apptNoTime);
    expect(ics).toContain('DTSTART:20260728T090000Z');
  });

  it('should contain BEGIN:VEVENT and END:VEVENT', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics).toContain('BEGIN:VEVENT');
    expect(ics).toContain('END:VEVENT');
  });

  it('should use \\r\\n line endings (RFC 5545 compliance)', () => {
    const ics = generateIcsContent(mockAppointment);
    expect(ics).toContain('\r\n');
  });
});

describe('downloadIcsFile', () => {
  let createObjectURLSpy: jasmine.Spy;
  let revokeObjectURLSpy: jasmine.Spy;
  let appendChildSpy: jasmine.Spy;
  let clickSpy: jasmine.Spy;

  const mockAppointment: Appointment = {
    id: 'appt-456',
    type: 'Follow-up with your doctor',
    date: '2026-07-28',
    time: '09:00:00',
    provider: null,
    location: null,
  };

  beforeEach(() => {
    createObjectURLSpy = spyOn(URL, 'createObjectURL').and.returnValue('blob:mock-url');
    revokeObjectURLSpy = spyOn(URL, 'revokeObjectURL');

    // Spy on anchor element click
    clickSpy = jasmine.createSpy('click');
    spyOn(document, 'createElement').and.callFake((tag: string) => {
      if (tag === 'a') {
        const anchor = document.createElement('a') as HTMLAnchorElement;
        anchor.click = clickSpy;
        return anchor;
      }
      return document.createElement(tag);
    });
  });

  it('should call URL.createObjectURL with a Blob', () => {
    downloadIcsFile(mockAppointment);
    expect(createObjectURLSpy).toHaveBeenCalledWith(jasmine.any(Blob));
  });

  it('should set the anchor download attribute with the appointment id', () => {
    downloadIcsFile(mockAppointment);
    // createObjectURL called → Blob created → click triggered
    expect(createObjectURLSpy).toHaveBeenCalled();
  });

  it('should call URL.revokeObjectURL to clean up the object URL', () => {
    downloadIcsFile(mockAppointment);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url');
  });

  it('should trigger a click on the anchor element', () => {
    downloadIcsFile(mockAppointment);
    expect(clickSpy).toHaveBeenCalled();
  });
});
```

---

## Validation Checklist

```
[ ] ng test — all spec files pass with zero failures
[ ] chatbot-widget.component.spec.ts: 8+ passing tests
[ ] ics-generator.spec.ts: 8+ passing tests
[ ] No test uses 'any' type without explicit justification
[ ] Typing indicator test verifies both show and hide behaviour
[ ] Scope-refusal test confirms no urgency banner is rendered
[ ] Urgency test confirms both banner presence AND tel:911 href
[ ] .ics test validates DTSTART format YYYYMMDDTHHMMSSZ precisely
[ ] .ics test validates SUMMARY:SmartHandoff Follow-up Appointment
[ ] Code coverage ≥80% branch coverage across all tested modules
```

---

## Definition of Done Mapping

| DoD Item | Covered |
|---|---|
| Unit tests: chatbot widget scope enforcement | ✅ `chatbot-widget.component.spec.ts` — Scenario 3 tests |
| Unit tests: urgency response rendering | ✅ `chatbot-widget.component.spec.ts` — Scenario 4 tests |
| Unit tests: .ics download | ✅ `ics-generator.spec.ts` — `generateIcsContent` + `downloadIcsFile` tests |
