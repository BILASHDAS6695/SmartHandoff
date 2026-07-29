/**
 * Unit tests for ChatbotWidgetComponent.
 *
 * Coverage:
 *   US-055 AC Scenario 3 — scope-refusal message rendered without client-side filtering
 *   US-055 AC Scenario 4 — urgency=true → red banner with <a href="tel:911"> link
 */
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { of, throwError, delay } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ChatbotWidgetComponent } from './chatbot-widget.component';
import { ChatbotService } from '../../services/chatbot.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { ChatResponse } from '../../models/chat.model';

describe('ChatbotWidgetComponent', () => {
  let fixture: ComponentFixture<ChatbotWidgetComponent>;
  let component: ChatbotWidgetComponent;
  let chatbotServiceSpy: any;
  let authServiceSpy: any;

  beforeEach(async () => {
    chatbotServiceSpy = {
      sendMessage: jest.fn(),
    };
    authServiceSpy = {
      getPatientClaim: jest.fn(),
    };
    authServiceSpy.getPatientClaim.mockReturnValue('ENC-001');

    await TestBed.configureTestingModule({
      imports: [ChatbotWidgetComponent, NoopAnimationsModule],
      providers: [
        { provide: ChatbotService, useValue: chatbotServiceSpy },
        { provide: AuthService, useValue: authServiceSpy },
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
      chatbotServiceSpy.sendMessage.mockReturnValue(of(response));
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
      chatbotServiceSpy.sendMessage.mockReturnValue(of(response));
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
      chatbotServiceSpy.sendMessage.mockReturnValue(of(normalResponse));

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
    // Return a response after a delay to simulate async
    chatbotServiceSpy.sendMessage.mockReturnValue(
      of({ message: 'Hello', urgency: false }).pipe(delay(100))
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
    chatbotServiceSpy.sendMessage.mockReturnValue(throwError(() => new Error('Network error')));

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
