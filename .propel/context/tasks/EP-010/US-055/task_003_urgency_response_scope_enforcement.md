---
id: TASK-003
title: "Urgency Response Display & LLM Scope Enforcement in Chatbot Widget"
user_story: US-055
epic: EP-010
sprint: 2
layer: Frontend
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-055/TASK-001, US-044]
---

# TASK-003: Urgency Response Display & LLM Scope Enforcement in Chatbot Widget

> **Story:** US-055 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-055 requires two safety-critical behaviours in the chatbot widget built in TASK-001:

1. **Urgency response rendering (AC Scenario 4):** When the API returns `urgency=true` (triggered server-side by US-044 urgency detection), the widget must display a full-width red banner with a prominent call-911 instruction and an `<a href="tel:911">` link within 10 seconds of the patient sending the message.

2. **Scope enforcement response display (AC Scenario 3):** When the LLM returns its scoped refusal message ("I can only answer questions about your own discharge instructions…"), that message must render clearly — this is enforced server-side; the widget must not suppress or alter scope-refusal messages in any way.

**Design references:**
- US-055 AC Scenario 3 — LLM scope constraint: chatbot cannot answer questions about other patients
- US-055 AC Scenario 4 — urgency=true → full-width red banner, call-911, `<a href="tel:911">` within 10 s
- US-055 DoD — "CSS override for `urgency=true` messages — full-width red banner with phone link"
- US-044 — Server-side urgency detection (triggers `urgency=true` in chat response)
- SEC-standards — PHI scope: `encounter_id` from JWT ensures server-side patient isolation

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 3 | Scope-refusal messages rendered as-is; no client-side filtering or alteration |
| Scenario 4 | `urgency=true` → full-width red banner with call-911 instruction and `<a href="tel:911">` link within 10 s |

---

## Implementation Steps

### 1. Add urgency banner to `chatbot-widget.component.html`

Replace the existing assistant message block with urgency-aware rendering:

```html
<!-- Inside the @for loop in chatbot-widget.component.html -->
@if (msg.isTyping) {
  <div class="message message--assistant message--typing" aria-label="Assistant is typing">
    <span class="dot"></span><span class="dot"></span><span class="dot"></span>
  </div>
} @else if (msg.urgency) {
  <!-- Urgency Banner — US-055 AC Scenario 4 -->
  <div class="urgency-banner" role="alert" aria-live="assertive">
    <mat-icon class="urgency-icon" aria-hidden="true">warning</mat-icon>
    <div class="urgency-content">
      <p class="urgency-heading">⚠️ Emergency — Call 911 Immediately</p>
      <p class="urgency-body">{{ msg.content }}</p>
      <a
        href="tel:911"
        class="urgency-call-btn"
        aria-label="Call 911 emergency services">
        <mat-icon aria-hidden="true">phone</mat-icon>
        Call 911
      </a>
    </div>
  </div>
} @else {
  <div
    class="message message--{{ msg.role }}"
    role="listitem">
    <p>{{ msg.content }}</p>
  </div>
}
```

### 2. Add urgency banner styles to `chatbot-widget.component.scss`

```scss
// Urgency banner — US-055 AC Scenario 4
// Full-width red banner with call-911 link; overrides standard message width constraint
.urgency-banner {
  width: 100%;
  background: #c62828;
  color: #fff;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  box-shadow: 0 2px 8px rgba(198, 40, 40, 0.4);

  .urgency-icon {
    font-size: 28px;
    flex-shrink: 0;
    margin-top: 2px;
  }

  .urgency-content {
    flex: 1;
  }

  .urgency-heading {
    font-weight: 700;
    font-size: 15px;
    margin: 0 0 6px;
  }

  .urgency-body {
    font-size: 13px;
    margin: 0 0 12px;
    line-height: 1.5;
  }

  .urgency-call-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #fff;
    color: #c62828;
    font-weight: 700;
    font-size: 14px;
    padding: 8px 16px;
    border-radius: 6px;
    text-decoration: none;
    transition: background 0.15s ease;

    &:hover,
    &:focus {
      background: #ffebee;
      outline: 2px solid #c62828;
      outline-offset: 2px;
    }
  }
}
```

### 3. Verify scope-enforcement response pass-through

No client-side changes are needed for AC Scenario 3 — the LLM scope refusal is enforced server-side (US-043/US-052). Confirm the following in code review:

- `ChatbotService.sendMessage()` returns the API response `message` string verbatim without filtering
- The template renders `{{ msg.content }}` without any conditional hiding based on content keywords
- No client-side keyword detection exists that could suppress or alter scope-refusal messages

Add an inline comment in `chatbot-widget.component.ts` within the `next` handler:

```typescript
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
```

### 4. Verify 10-second urgency display requirement

The 10-second requirement (US-055 AC Scenario 4) is a combined budget:

| Phase | Budget |
|-------|--------|
| Patient types and sends message | ~1 s |
| API round-trip (POST /api/v1/chat with Gemini Flash) | ≤3 s (TR-006) |
| Urgency detection + response construction (US-044) | ≤5 s server-side budget |
| Typing indicator removal + banner render | <100 ms (client) |
| **Total** | **≤9.1 s** — within 10 s budget |

No additional client-side optimisation is required. The typing indicator (TASK-001) already provides visual feedback during the wait.

---

## Validation Checklist

```
[ ] Send "I have severe chest pain" → urgency banner appears with red background
[ ] Urgency banner is full-width inside the chat panel (not constrained to 80% message width)
[ ] Banner contains: warning icon, "Emergency — Call 911 Immediately" heading, response text, Call 911 button
[ ] Call 911 button is an <a href="tel:911"> link (inspect element to confirm)
[ ] Call 911 button is keyboard-focusable (Tab key reaches it)
[ ] Urgency banner has role="alert" and aria-live="assertive" for screen reader announcement
[ ] Non-urgency messages are NOT displayed as urgency banners
[ ] Scope-refusal message ("I can only answer questions about your own discharge instructions…")
    renders as a normal assistant message — not suppressed, not altered
[ ] No console.log containing patient question or PHI
[ ] Response time from send to banner display ≤10 s (measure in DevTools Network tab)
```

---

## Definition of Done Mapping

| DoD Item | Covered |
|---|---|
| Urgency response: CSS override for `urgency=true` messages — full-width red banner with phone link | ✅ This task |
| Scenario 3: scope-enforcement message rendered without client-side filtering | ✅ This task |
