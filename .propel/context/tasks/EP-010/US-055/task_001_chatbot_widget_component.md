---
id: TASK-001
title: "ChatbotWidgetComponent — Floating Bubble, Expand/Collapse, Message History & Typing Indicator"
user_story: US-055
epic: EP-010
sprint: 2
layer: Frontend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-052, US-043]
---

# TASK-001: ChatbotWidgetComponent — Floating Bubble, Expand/Collapse, Message History & Typing Indicator

> **Story:** US-055 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-055 requires a standalone Angular chatbot widget embedded in `PatientPortalModule`. The widget:

1. Renders as a floating bubble (bottom-right) on the patient portal
2. Expands to a side panel on desktop and full-screen overlay on mobile (85% viewport height)
3. Maintains message history with a typing indicator (`{isTyping: true}` pseudo-message) while waiting for API response
4. Sends messages to `POST /api/v1/chat` using the patient JWT from `PatientAuthService`, including `encounter_id` extracted from the JWT claim
5. Renders each response message with support for `urgency=true` flag (handled in TASK-003)

**Design references:**
- design.md §3.4 — `features/patient-portal/` lazy-loaded module
- design.md §4.1 — Angular 17, Angular Material, `@microsoft/signalr`, PWA
- US-055 AC Scenario 1 — response displayed within 3 seconds; connects to `POST /api/v1/chat` with patient JWT
- US-055 AC Scenario 4 — urgency detection renders emergency banner (CSS hook prepared here; logic in TASK-003)
- US-055 Technical Notes — standalone component; mobile overlay vs. desktop panel; typing indicator
- TR-006 — chatbot response time <3 seconds (Gemini Flash model used server-side)
- ADR-005 — Angular 17 PWA; lazy-loaded feature modules

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Widget sends `POST /api/v1/chat` with JWT; response rendered ≤3 s |
| Scenario 4 (partial) | CSS class hook `urgency-message` attached to messages with `urgency=true` — full display logic in TASK-003 |

---

## Implementation Steps

### 1. Scaffold component and service files

```bash
mkdir -p frontend/src/app/features/patient-portal/components/chatbot-widget
touch frontend/src/app/features/patient-portal/components/chatbot-widget/chatbot-widget.component.ts
touch frontend/src/app/features/patient-portal/components/chatbot-widget/chatbot-widget.component.html
touch frontend/src/app/features/patient-portal/components/chatbot-widget/chatbot-widget.component.scss
touch frontend/src/app/features/patient-portal/services/chatbot.service.ts
touch frontend/src/app/features/patient-portal/models/chat.model.ts
```

### 2. Define `frontend/src/app/features/patient-portal/models/chat.model.ts`

```typescript
/**
 * Chat domain models for the patient chatbot widget.
 *
 * Design refs:
 *   US-055 Technical Notes — typing indicator as pseudo-message; urgency flag
 *   US-055 AC Scenario 4  — urgency=true triggers emergency display
 */

export type MessageRole = 'patient' | 'assistant';

export interface ChatMessage {
  /** Unique client-side ID for tracking within the message list. */
  id: string;
  role: MessageRole;
  content: string;
  /** When true, renders the urgency banner (TASK-003). */
  urgency?: boolean;
  /** When true, this is a transient typing-indicator pseudo-message. */
  isTyping?: boolean;
  timestamp: Date;
}

export interface ChatRequest {
  encounter_id: string;
  message: string;
}

export interface ChatResponse {
  message: string;
  urgency: boolean;
}
```

### 3. Implement `frontend/src/app/features/patient-portal/services/chatbot.service.ts`

```typescript
/**
 * ChatbotService — sends patient messages to POST /api/v1/chat.
 *
 * Authentication: patient JWT injected automatically by JwtInterceptor (core/auth).
 * The encounter_id is extracted from the JWT 'encounter_id' claim via PatientAuthService.
 *
 * Design refs:
 *   US-055 AC Scenario 1 — POST /api/v1/chat with patient JWT
 *   US-055 AC Scenario 3 — encounter_id from JWT ensures server-side scope enforcement
 *   TR-006              — chatbot response time target <3 seconds
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { PatientAuthService } from '../../auth/services/patient-auth.service';
import { ChatRequest, ChatResponse } from '../models/chat.model';

@Injectable({ providedIn: 'root' })
export class ChatbotService {
  private readonly http = inject(HttpClient);
  private readonly patientAuth = inject(PatientAuthService);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/chat`;

  /**
   * Send a patient message to the chat API.
   * encounter_id is sourced from the JWT claim — never passed by the caller.
   */
  sendMessage(userMessage: string): Observable<ChatResponse> {
    const encounterId = this.patientAuth.getEncounterId();
    const body: ChatRequest = { encounter_id: encounterId, message: userMessage };
    return this.http.post<ChatResponse>(this.baseUrl, body);
  }
}
```

### 4. Implement `chatbot-widget.component.ts`

```typescript
/**
 * ChatbotWidgetComponent — floating chat bubble for the patient portal.
 *
 * Layout behaviour:
 *   Desktop: fixed bottom-right panel (400 × 560 px), expand/collapse toggle
 *   Mobile (<768 px): full-screen overlay at 85% viewport height when expanded
 *
 * Typing indicator: a pseudo ChatMessage with isTyping=true is pushed to
 * messages$ while awaiting the API response, then replaced on arrival.
 *
 * Design refs:
 *   US-055 DoD       — standalone Angular component; PatientPortalModule import
 *   US-055 Technical Notes — mobile overlay; typing indicator
 *   ADR-005          — Angular 17 standalone components
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl, Validators } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { Subject, takeUntil } from 'rxjs';
import { v4 as uuidv4 } from 'uuid';
import { ChatbotService } from '../../services/chatbot.service';
import { ChatMessage } from '../../models/chat.model';

@Component({
  selector: 'app-chatbot-widget',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MatIconModule, MatButtonModule, MatInputModule],
  templateUrl: './chatbot-widget.component.html',
  styleUrls: ['./chatbot-widget.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatbotWidgetComponent implements OnDestroy {
  private readonly chatbotService = inject(ChatbotService);
  private readonly destroy$ = new Subject<void>();

  /** Controls expand/collapse state of the widget panel. */
  readonly isOpen = signal(false);

  /** Ordered list of chat messages including typing indicator pseudo-messages. */
  readonly messages = signal<ChatMessage[]>([]);

  /** Tracks whether an API request is in-flight. */
  readonly isSending = signal(false);

  readonly messageControl = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.maxLength(1000)],
  });

  toggle(): void {
    this.isOpen.update(open => !open);
  }

  sendMessage(): void {
    if (this.messageControl.invalid || this.isSending()) return;

    const userText = this.messageControl.value.trim();
    if (!userText) return;

    // Append the patient's message
    this.appendMessage({ role: 'patient', content: userText });
    this.messageControl.reset();
    this.isSending.set(true);

    // Show typing indicator
    const typingId = this.appendTypingIndicator();

    this.chatbotService
      .sendMessage(userText)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          this.removeTypingIndicator(typingId);
          this.appendMessage({
            role: 'assistant',
            content: response.message,
            urgency: response.urgency,
          });
          this.isSending.set(false);
        },
        error: () => {
          this.removeTypingIndicator(typingId);
          this.appendMessage({
            role: 'assistant',
            content: 'Sorry, I am unable to respond right now. Please try again later.',
          });
          this.isSending.set(false);
        },
      });
  }

  private appendMessage(partial: Omit<ChatMessage, 'id' | 'timestamp'>): void {
    const msg: ChatMessage = { id: uuidv4(), timestamp: new Date(), ...partial };
    this.messages.update(msgs => [...msgs, msg]);
  }

  private appendTypingIndicator(): string {
    const id = uuidv4();
    const indicator: ChatMessage = {
      id,
      role: 'assistant',
      content: '',
      isTyping: true,
      timestamp: new Date(),
    };
    this.messages.update(msgs => [...msgs, indicator]);
    return id;
  }

  private removeTypingIndicator(id: string): void {
    this.messages.update(msgs => msgs.filter(m => m.id !== id));
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
```

### 5. Implement `chatbot-widget.component.html`

```html
<!-- Chatbot Widget — floating bubble + expandable panel
     US-055 DoD: floating chat bubble bottom-right; expand/collapse; message history; typing indicator
     US-055 AC Scenario 4: urgency-message class applied for TASK-003 CSS override
-->

<!-- Floating bubble trigger -->
<button
  mat-fab
  color="primary"
  class="chatbot-bubble"
  aria-label="Open patient chatbot"
  (click)="toggle()">
  <mat-icon>{{ isOpen() ? 'close' : 'chat' }}</mat-icon>
</button>

<!-- Chat panel -->
@if (isOpen()) {
  <section class="chatbot-panel" role="dialog" aria-label="Patient chatbot">
    <header class="chatbot-header">
      <span>Ask your care assistant</span>
    </header>

    <div class="chatbot-messages" aria-live="polite" aria-atomic="false">
      @for (msg of messages(); track msg.id) {
        @if (msg.isTyping) {
          <div class="message message--assistant message--typing" aria-label="Assistant is typing">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          </div>
        } @else {
          <div
            class="message message--{{ msg.role }}"
            [class.urgency-message]="msg.urgency"
            role="listitem">
            <p>{{ msg.content }}</p>
          </div>
        }
      }
    </div>

    <form class="chatbot-input" (ngSubmit)="sendMessage()" autocomplete="off">
      <mat-form-field appearance="outline" class="chatbot-field">
        <input
          matInput
          [formControl]="messageControl"
          placeholder="Type your question…"
          aria-label="Chat message input"
          (keydown.enter)="sendMessage()" />
      </mat-form-field>
      <button
        mat-icon-button
        color="primary"
        type="submit"
        [disabled]="isSending() || messageControl.invalid"
        aria-label="Send message">
        <mat-icon>send</mat-icon>
      </button>
    </form>
  </section>
}
```

### 6. Implement `chatbot-widget.component.scss`

```scss
// ChatbotWidget styles
// US-055 Technical Notes: mobile 85% viewport height; desktop right-side panel
// US-055 DoD: mobile-friendly; urgency CSS override in TASK-003

:host {
  --widget-width: 400px;
  --widget-height: 560px;
}

.chatbot-bubble {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 1000;
}

.chatbot-panel {
  position: fixed;
  bottom: 90px;
  right: 24px;
  width: var(--widget-width);
  height: var(--widget-height);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  z-index: 999;
  overflow: hidden;

  @media (max-width: 767px) {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    width: 100%;
    height: 85vh;
    bottom: 0;
    border-radius: 0;
  }
}

.chatbot-header {
  padding: 16px;
  background: #1565c0;
  color: #fff;
  font-weight: 600;
  font-size: 15px;
}

.chatbot-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;

  &--patient {
    align-self: flex-end;
    background: #e3f2fd;
    color: #0d47a1;
  }

  &--assistant {
    align-self: flex-start;
    background: #f5f5f5;
    color: #212121;
  }

  &--typing {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 12px 14px;

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #9e9e9e;
      animation: blink 1.4s infinite both;

      &:nth-child(2) { animation-delay: 0.2s; }
      &:nth-child(3) { animation-delay: 0.4s; }
    }
  }
}

@keyframes blink {
  0%, 80%, 100% { opacity: 0; }
  40% { opacity: 1; }
}

.chatbot-input {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-top: 1px solid #e0e0e0;

  .chatbot-field {
    flex: 1;
  }
}
```

### 7. Register `ChatbotWidgetComponent` in `PatientPortalModule`

In `frontend/src/app/features/patient-portal/patient-portal.module.ts`, add to the `imports` array:

```typescript
import { ChatbotWidgetComponent } from './components/chatbot-widget/chatbot-widget.component';

// Inside @NgModule imports and exports arrays:
imports: [
  // ...existing imports
  ChatbotWidgetComponent,
],
```

And embed the selector in the patient portal shell template:

```html
<!-- patient-portal.component.html — append below main content -->
<app-chatbot-widget></app-chatbot-widget>
```

---

## Validation Checklist

```
[ ] Widget bubble renders at bottom-right — does not overlap navigation
[ ] Click bubble → panel expands; click again → panel collapses
[ ] Typing indicator (three animated dots) appears immediately on send
[ ] Typing indicator disappears when response arrives
[ ] Message history scrolls — older messages remain visible
[ ] On mobile viewport (<768 px): panel fills 85% viewport height
[ ] Network tab: POST /api/v1/chat called with Authorization: Bearer <patient-jwt>
[ ] Request body contains encounter_id matching the JWT claim
[ ] Response rendered in ≤3 s under normal conditions (TR-006)
[ ] No PHI appears in browser console logs (SEC-standards, BR-020)
[ ] 'urgency-message' CSS class present on messages where urgency=true (TASK-003 hook)
[ ] Angular strict mode passes — no 'any' types
[ ] No accessibility violations: all interactive elements keyboard-navigable (WCAG 2.2 AA)
```

---

## Definition of Done Mapping

| DoD Item | Covered |
|---|---|
| `ChatbotWidgetComponent`: floating bubble, expand/collapse, message history, typing indicator | ✅ This task |
| Widget uses patient JWT from `PatientAuthService`; sends `encounter_id` from JWT claim | ✅ This task |
| Mobile-friendly: chatbot widget uses 85% viewport height when expanded on mobile | ✅ This task |
