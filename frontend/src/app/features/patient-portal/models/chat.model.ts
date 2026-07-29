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
