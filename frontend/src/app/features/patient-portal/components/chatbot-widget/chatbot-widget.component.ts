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
import { MatFormFieldModule } from '@angular/material/form-field';
import { Subject, takeUntil } from 'rxjs';
import { v4 as uuidv4 } from 'uuid';
import { ChatbotService } from '../../services/chatbot.service';
import { ChatMessage } from '../../models/chat.model';

@Component({
  selector: 'app-chatbot-widget',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatIconModule,
    MatButtonModule,
    MatInputModule,
    MatFormFieldModule,
  ],
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
          // NOTE: Do NOT filter or alter the response message on the client side.
          // Scope enforcement is handled server-side (US-043, US-052).
          // Scope-refusal messages must render as-is to inform the patient.
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
    // Scroll to bottom on next tick
    setTimeout(() => {
      const messagesContainer = document.querySelector('.chatbot-messages');
      if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }
    });
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
    // Scroll to bottom
    setTimeout(() => {
      const messagesContainer = document.querySelector('.chatbot-messages');
      if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }
    });
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
