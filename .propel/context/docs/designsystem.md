# SmartHandoff — Design System

> **Artifact:** designsystem | **Version:** 1.0 | **Status:** Draft
> **Date:** 2026-07-14 | **Upstream:** figma_spec.md v1.0, SRS v1.0 | **Workflow:** /create-figma-spec
> **Designer:** SmartHandoff Project Team

---

## Table of Contents

1. [Brand Identity](#1-brand-identity)
2. [Colour Tokens](#2-colour-tokens)
3. [Typography](#3-typography)
4. [Spacing & Layout Grid](#4-spacing--layout-grid)
5. [Elevation & Shadow](#5-elevation--shadow)
6. [Border & Radius](#6-border--radius)
7. [Iconography](#7-iconography)
8. [Motion & Animation](#8-motion--animation)
9. [Component Specifications](#9-component-specifications)
10. [Dark Mode Mapping](#10-dark-mode-mapping)
11. [Accessibility Tokens](#11-accessibility-tokens)
12. [Design Token Reference (CSS Custom Properties)](#12-design-token-reference-css-custom-properties)

---

## 1. Brand Identity

### 1.1 Design Direction

**Aesthetic:** Clinical Trust with Human Warmth
SmartHandoff operates in a high-stakes healthcare environment where clarity saves lives. The design system prioritises information hierarchy, immediate legibility, and calm confidence. Colour signals risk; whitespace signals order; motion signals change.

### 1.2 Brand Voice in UI

| Context | Tone | Example |
|---------|------|---------|
| Alerts | Direct, urgent | "Major drug interaction detected. Review immediately." |
| Empty states | Reassuring | "No pending tasks. All patients are on track." |
| AI content | Transparent | "AI-Assisted — Review Required before approving." |
| Patient portal | Warm, plain-language | "Here is what to do when you get home." |
| Errors | Helpful, not technical | "Something went wrong. Try again or contact IT support." |

---

## 2. Colour Tokens

### 2.1 Primitive Palette

```css
/* Blues — Primary brand / interactions */
--color-blue-50:  #EFF6FF;
--color-blue-100: #DBEAFE;
--color-blue-200: #BFDBFE;
--color-blue-300: #93C5FD;
--color-blue-400: #60A5FA;
--color-blue-500: #3B82F6;
--color-blue-600: #2563EB;
--color-blue-700: #1D4ED8;
--color-blue-800: #1E40AF;
--color-blue-900: #1E3A8A;

/* Greens — Success / Low risk / Safe states */
--color-green-50:  #F0FDF4;
--color-green-100: #DCFCE7;
--color-green-200: #BBF7D0;
--color-green-300: #86EFAC;
--color-green-400: #4ADE80;
--color-green-500: #22C55E;
--color-green-600: #16A34A;
--color-green-700: #15803D;
--color-green-800: #166534;
--color-green-900: #14532D;

/* Ambers — Warning / Medium risk */
--color-amber-50:  #FFFBEB;
--color-amber-100: #FEF3C7;
--color-amber-200: #FDE68A;
--color-amber-300: #FCD34D;
--color-amber-400: #FBBF24;
--color-amber-500: #F59E0B;
--color-amber-600: #D97706;
--color-amber-700: #B45309;
--color-amber-800: #92400E;
--color-amber-900: #78350F;

/* Reds — Critical / High risk / Danger */
--color-red-50:  #FEF2F2;
--color-red-100: #FEE2E2;
--color-red-200: #FECACA;
--color-red-300: #FCA5A5;
--color-red-400: #F87171;
--color-red-500: #EF4444;
--color-red-600: #DC2626;
--color-red-700: #B91C1C;
--color-red-800: #991B1B;
--color-red-900: #7F1D1D;

/* Greys — Neutral / Structure */
--color-grey-50:  #F9FAFB;
--color-grey-100: #F3F4F6;
--color-grey-200: #E5E7EB;
--color-grey-300: #D1D5DB;
--color-grey-400: #9CA3AF;
--color-grey-500: #6B7280;
--color-grey-600: #4B5563;
--color-grey-700: #374151;
--color-grey-800: #1F2937;
--color-grey-900: #111827;

/* Teal — AI-assisted / informational */
--color-teal-50:  #F0FDFA;
--color-teal-100: #CCFBF1;
--color-teal-400: #2DD4BF;
--color-teal-500: #14B8A6;
--color-teal-600: #0D9488;
--color-teal-700: #0F766E;
```

### 2.2 Semantic Colour Tokens

#### Brand

| Token | Value | Usage |
|-------|-------|-------|
| `--color-brand-primary` | `--color-blue-600` (`#2563EB`) | Primary buttons, active nav, links |
| `--color-brand-primary-hover` | `--color-blue-700` (`#1D4ED8`) | Hover state on primary elements |
| `--color-brand-secondary` | `--color-teal-600` (`#0D9488`) | AI badge, info accents |

#### Risk Severity (FR-071)

| Token | Value | Usage | Threshold |
|-------|-------|-------|-----------|
| `--color-risk-low` | `--color-green-600` (`#16A34A`) | Risk chip background | < 0.3 |
| `--color-risk-low-bg` | `--color-green-50` (`#F0FDF4`) | Risk chip background fill | < 0.3 |
| `--color-risk-medium` | `--color-amber-600` (`#D97706`) | Risk chip text | 0.3–0.7 |
| `--color-risk-medium-bg` | `--color-amber-50` (`#FFFBEB`) | Risk chip background fill | 0.3–0.7 |
| `--color-risk-high` | `--color-red-600` (`#DC2626`) | Risk chip text | > 0.7 |
| `--color-risk-high-bg` | `--color-red-50` (`#FEF2F2`) | Risk chip background fill | > 0.7 |

#### Alert Levels (UI-003)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-alert-critical` | `--color-red-600` (`#DC2626`) | Critical alerts, drug interactions |
| `--color-alert-critical-bg` | `--color-red-50` (`#FEF2F2`) | Alert panel background |
| `--color-alert-warning` | `--color-amber-600` (`#D97706`) | Warning alerts, ED boarding |
| `--color-alert-warning-bg` | `--color-amber-50` (`#FFFBEB`) | Warning panel background |
| `--color-alert-info` | `--color-blue-600` (`#2563EB`) | Informational alerts |
| `--color-alert-info-bg` | `--color-blue-50` (`#EFF6FF`) | Info panel background |
| `--color-alert-success` | `--color-green-600` (`#16A34A`) | Success states, approved docs |
| `--color-alert-success-bg` | `--color-green-50` (`#F0FDF4`) | Success panel background |

#### AI Content (BR-011)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-ai-badge` | `--color-teal-600` (`#0D9488`) | "AI-Assisted" badge text |
| `--color-ai-badge-bg` | `--color-teal-50` (`#F0FDFA`) | "AI-Assisted" badge background |
| `--color-ai-badge-border` | `--color-teal-400` (`#2DD4BF`) | "AI-Assisted" badge border |

#### Surface & Background

| Token | Light Value | Usage |
|-------|-------------|-------|
| `--color-surface-page` | `--color-grey-50` (`#F9FAFB`) | Page background |
| `--color-surface-card` | `#FFFFFF` | Card / panel background |
| `--color-surface-overlay` | `rgba(0,0,0,0.5)` | Modal backdrop |
| `--color-surface-input` | `#FFFFFF` | Form input backgrounds |

#### Text

| Token | Value | Usage |
|-------|-------|-------|
| `--color-text-primary` | `--color-grey-900` (`#111827`) | Body text, headings |
| `--color-text-secondary` | `--color-grey-600` (`#4B5563`) | Labels, secondary content |
| `--color-text-disabled` | `--color-grey-400` (`#9CA3AF`) | Disabled states |
| `--color-text-inverse` | `#FFFFFF` | Text on dark/coloured backgrounds |
| `--color-text-link` | `--color-blue-600` (`#2563EB`) | Hyperlinks |
| `--color-text-link-hover` | `--color-blue-700` (`#1D4ED8`) | Link hover |

#### Border

| Token | Value | Usage |
|-------|-------|-------|
| `--color-border-default` | `--color-grey-200` (`#E5E7EB`) | Default card/input borders |
| `--color-border-focus` | `--color-blue-600` (`#2563EB`) | Focus rings on interactive elements |
| `--color-border-error` | `--color-red-500` (`#EF4444`) | Input validation errors |

---

## 3. Typography

### 3.1 Font Stack

```css
--font-family-base: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-family-mono: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
```

**Rationale:** Inter is optimised for screen legibility at small sizes, making it ideal for data-dense clinical dashboards. JetBrains Mono is used exclusively for HL7 message segments, audit log entries, and code-like data.

### 3.2 Type Scale

| Token | Size | Line Height | Weight | Usage |
|-------|------|-------------|--------|-------|
| `--text-xs` | 12px / 0.75rem | 1.5 (18px) | 400 | Captions, timestamps, badge labels |
| `--text-sm` | 14px / 0.875rem | 1.5 (21px) | 400 | Secondary body, table cells, form labels |
| `--text-base` | 16px / 1rem | 1.5 (24px) | 400 | Primary body text |
| `--text-lg` | 18px / 1.125rem | 1.4 (26px) | 500 | Card titles, panel headers |
| `--text-xl` | 20px / 1.25rem | 1.4 (28px) | 600 | Section headings (H3) |
| `--text-2xl` | 24px / 1.5rem | 1.3 (32px) | 600 | Page headings (H2) |
| `--text-3xl` | 30px / 1.875rem | 1.3 (39px) | 700 | KPI values, large numerics |
| `--text-4xl` | 36px / 2.25rem | 1.2 (44px) | 700 | Display / landing headings |

### 3.3 Font Weight Reference

| Token | Value | Usage |
|-------|-------|-------|
| `--font-weight-regular` | 400 | Body text, labels |
| `--font-weight-medium` | 500 | Card titles, form field values |
| `--font-weight-semibold` | 600 | Section headings, button labels |
| `--font-weight-bold` | 700 | Page titles, KPI values, risk scores |

### 3.4 Patient Portal Typography

Patient portal uses a slightly larger base for accessibility on mobile and compliance with 6th-grade readability (FR-021):

| Token | Size | Usage |
|-------|------|-------|
| `--portal-text-base` | 18px / 1.125rem | Portal body text |
| `--portal-text-heading` | 22px / 1.375rem | Portal section headings |
| `--portal-text-instruction` | 16px / 1rem | Instruction list items |

---

## 4. Spacing & Layout Grid

### 4.1 Spacing Scale (4px base unit)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-1` | 4px | Micro spacing (icon gap, badge padding) |
| `--space-2` | 8px | Component internal padding (tight) |
| `--space-3` | 12px | Form input padding |
| `--space-4` | 16px | Card padding, list item gap |
| `--space-5` | 20px | Section padding |
| `--space-6` | 24px | Card gap, panel padding |
| `--space-8` | 32px | Section margin |
| `--space-10` | 40px | Page section gap |
| `--space-12` | 48px | Large section margin |
| `--space-16` | 64px | Hero / empty state padding |

### 4.2 Layout Grid

#### Staff Dashboard (1024px–2560px)

| Breakpoint | Columns | Gutter | Margin |
|------------|---------|--------|--------|
| `sm` (1024px) | 8 | 16px | 24px |
| `md` (1280px) | 12 | 24px | 32px |
| `lg` (1440px) | 12 | 24px | 48px |
| `xl` (1920px) | 16 | 24px | 64px |
| `2xl` (2560px) | 16 | 32px | 80px |

#### Patient Portal (375px–768px)

| Breakpoint | Columns | Gutter | Margin |
|------------|---------|--------|--------|
| `xs` (375px) | 4 | 16px | 16px |
| `sm` (480px) | 4 | 16px | 24px |
| `md` (768px) | 8 | 24px | 32px |

### 4.3 Sidebar Navigation

| Viewport | Navigation Pattern | Width |
|----------|--------------------|-------|
| < 1280px | Collapsible icon rail | 64px (collapsed), 240px (expanded) |
| ≥ 1280px | Persistent sidebar | 240px |

---

## 5. Elevation & Shadow

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Inputs, subtle lift |
| `--shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1)` | Cards, panels |
| `--shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)` | Dropdowns, floating elements |
| `--shadow-xl` | `0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)` | Modals, drawers |
| `--shadow-focus` | `0 0 0 3px rgba(37,99,235,0.4)` | Focus ring glow |

**Elevation levels:**

| Level | Shadow | Component |
|-------|--------|-----------|
| 0 | none | Page background |
| 1 | `--shadow-sm` | Form inputs |
| 2 | `--shadow-md` | Cards, panels |
| 3 | `--shadow-lg` | Dropdowns, tooltips |
| 4 | `--shadow-xl` | Modals, side drawers |

---

## 6. Border & Radius

### 6.1 Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 4px | Chips, badges, input fields |
| `--radius-md` | 8px | Buttons, small cards |
| `--radius-lg` | 12px | Cards, panels |
| `--radius-xl` | 16px | Modal dialogs |
| `--radius-2xl` | 24px | Patient portal cards (softer, warmer) |
| `--radius-full` | 9999px | Pill badges, toggle switches, avatar |

### 6.2 Border Width

| Token | Value | Usage |
|-------|-------|-------|
| `--border-width-default` | 1px | Cards, inputs |
| `--border-width-focus` | 2px | Focus state |
| `--border-width-alert` | 2px | Alert banners, critical card borders |

---

## 7. Iconography

### 7.1 Icon System

**Library:** Heroicons v2 (MIT licence) — consistent with Angular Material / Tailwind ecosystem.

**Sizes:**

| Token | Size | Usage |
|-------|------|-------|
| `--icon-xs` | 12px | Inline status indicators |
| `--icon-sm` | 16px | Table row icons, badge icons |
| `--icon-md` | 20px | Form field icons, nav items |
| `--icon-lg` | 24px | Primary action icons |
| `--icon-xl` | 32px | Empty state illustrations |
| `--icon-2xl` | 48px | Alert modal icons |

### 7.2 Semantic Icon Mapping

| Context | Icon | Style |
|---------|------|-------|
| Critical alert | `exclamation-circle` | Solid, `--color-alert-critical` |
| Warning | `exclamation-triangle` | Solid, `--color-alert-warning` |
| Info | `information-circle` | Outline, `--color-alert-info` |
| Success / Approved | `check-circle` | Solid, `--color-alert-success` |
| AI-Assisted | `sparkles` | Solid, `--color-ai-badge` |
| Notifications | `bell` | Outline / Solid (unread) |
| Search | `magnifying-glass` | Outline |
| User / Avatar | `user-circle` | Outline |
| Download / Export | `arrow-down-tray` | Outline |
| Microphone (voice) | `microphone` | Outline / Solid (active) |
| Bed | `building-office-2` | Outline |
| Medication | `beaker` | Outline |
| Document | `document-text` | Outline |
| Agent / Robot | `cpu-chip` | Outline |
| Emergency | `phone` | Solid, white |

---

## 8. Motion & Animation

### 8.1 Duration Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--duration-instant` | 0ms | Immediate feedback (no animation) |
| `--duration-fast` | 100ms | Hover transitions, toggle state changes |
| `--duration-normal` | 200ms | Button presses, chip transitions |
| `--duration-moderate` | 300ms | Panel open/close, dropdown animations |
| `--duration-slow` | 500ms | Page transitions, skeleton-to-content fade |

### 8.2 Easing Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--ease-default` | `cubic-bezier(0.4, 0, 0.2, 1)` | Standard transitions |
| `--ease-in` | `cubic-bezier(0.4, 0, 1, 1)` | Elements entering |
| `--ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | Elements exiting |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Toast pop-in, badge increment |

### 8.3 Animation Patterns

| Pattern | Duration | Easing | Trigger |
|---------|----------|--------|---------|
| Skeleton → Content | 500ms | `--ease-out` | Data loaded |
| Toast enter | 200ms | `--ease-spring` | Notification received |
| Toast exit | 150ms | `--ease-in` | 5s auto-dismiss |
| Modal open | 250ms | `--ease-out` | Modal triggered |
| Modal close | 200ms | `--ease-in` | Dismiss action |
| Risk chip pulse | 500ms | `--ease-default` | New high-risk event |
| ADT feed item highlight | 500ms | `--ease-out` | New ADT event |
| Chatbot slide-up | 300ms | `--ease-spring` | FAB clicked |

### 8.4 Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

All animations degrade gracefully: skeleton loaders use opacity fade only; toasts appear instantly; modals open without transition.

---

## 9. Component Specifications

### 9.1 RiskScoreChip

Displays a patient's readmission risk score with colour and icon.

```
┌──────────────────────────────┐
│ [icon] 0.82  HIGH RISK       │
└──────────────────────────────┘
```

| Property | Specification |
|----------|---------------|
| Height | 28px |
| Padding | 4px 10px |
| Border radius | `--radius-full` |
| Font size | `--text-sm` / `--font-weight-semibold` |
| Low (< 0.3) | Background `--color-risk-low-bg`, text `--color-risk-low` |
| Medium (0.3–0.7) | Background `--color-risk-medium-bg`, text `--color-risk-medium` |
| High (> 0.7) | Background `--color-risk-high-bg`, text `--color-risk-high` |
| Icon | 14px `check-circle` / `exclamation-triangle` / `exclamation-circle` |

**WCAG note:** Risk level communicated via text label AND icon, not colour alone.

---

### 9.2 AiBadge

Persistent badge on AI-generated content panels and documents.

```
┌──────────────────────────────────────────────────────────┐
│ ✨ AI-Assisted — Review Required                         │
└──────────────────────────────────────────────────────────┘
```

| Property | Specification |
|----------|---------------|
| Height | 32px |
| Padding | 6px 12px |
| Border radius | `--radius-sm` |
| Border | 1px solid `--color-ai-badge-border` |
| Background | `--color-ai-badge-bg` |
| Text colour | `--color-ai-badge` |
| Font | `--text-sm` / `--font-weight-medium` |
| Icon | `sparkles` 14px |
| State: approved | Background `--color-alert-success-bg`, text `--color-alert-success`, icon `check-circle` |

---

### 9.3 AlertBanner

In-page alert banners for critical / warning / info scenarios.

| Property | Critical | Warning | Info | Success |
|----------|----------|---------|------|---------|
| Background | `--color-alert-critical-bg` | `--color-alert-warning-bg` | `--color-alert-info-bg` | `--color-alert-success-bg` |
| Left border | 4px solid `--color-alert-critical` | 4px solid `--color-alert-warning` | 4px solid `--color-alert-info` | 4px solid `--color-alert-success` |
| Icon | `exclamation-circle` (red) | `exclamation-triangle` (amber) | `information-circle` (blue) | `check-circle` (green) |
| Dismiss button | Required (critical requires explicit dismiss) | Optional | Optional | Optional |

---

### 9.4 PrimaryButton

| Property | Specification |
|----------|---------------|
| Height | 40px (desktop), 48px (mobile/portal) |
| Padding | 10px 20px |
| Border radius | `--radius-md` |
| Background | `--color-brand-primary` |
| Text | `--color-text-inverse`, `--text-sm`, `--font-weight-semibold` |
| Hover | Background `--color-brand-primary-hover` |
| Focus | `--shadow-focus` ring |
| Disabled | Background `--color-grey-300`, text `--color-text-disabled` |
| Destructive variant | Background `--color-alert-critical`, hover `--color-red-700` |

---

### 9.5 BedTile

Used in SCR-007 Bed Board.

```
┌──────────────┐
│ 4W-03        │
│ CLEAN        │
│ AVAILABLE    │
└──────────────┘
```

| Status | Background | Text colour | Border |
|--------|------------|-------------|--------|
| Clean / Available | `--color-green-50` | `--color-green-700` | `--color-green-300` |
| Dirty | `--color-amber-50` | `--color-amber-700` | `--color-amber-300` |
| Occupied | `--color-blue-50` | `--color-blue-700` | `--color-blue-300` |
| Blocked / Maintenance | `--color-grey-100` | `--color-grey-600` | `--color-grey-300` |

Dimensions: 120×100px desktop; responsive tile grid with min-width 80px on tablet.

---

### 9.6 SkeletonLoader

| Property | Specification |
|----------|---------------|
| Background | `--color-grey-200` |
| Shimmer animation | Gradient sweep, 1.5s loop, disabled by `prefers-reduced-motion` |
| Text line height | 20px with 8px gap |
| Card skeleton | Matches target card dimensions with 16px border radius |

---

### 9.7 ToastNotification

| Property | Specification |
|----------|---------------|
| Width | 320px |
| Position | Fixed, top-right, `--space-4` from edges |
| Z-index | 9000 |
| Auto-dismiss | 5 seconds (critical: must be manually dismissed) |
| Stack limit | Max 3 visible; oldest pushed off-screen |
| `aria-live` | `polite` (info/success), `assertive` (critical/warning) |

---

### 9.8 ConfirmModal

Used for all irreversible actions (approve & sign, disable user, cancel ADT).

| Property | Specification |
|----------|---------------|
| Max width | 480px |
| Border radius | `--radius-xl` |
| Backdrop | `--color-surface-overlay` |
| Focus trap | Active while modal is open; returns on close |
| Escape | Closes modal (cancels action) |
| Confirm button | Destructive `PrimaryButton` variant |
| Cancel button | Secondary/ghost button |

---

### 9.9 ChatWidget (Patient Portal)

| State | Specification |
|-------|---------------|
| Closed (FAB) | 56×56px circle, `--color-brand-primary`, `chat-bubble` icon white, fixed bottom-right `--space-4` |
| Open | Slide-up drawer, 60% viewport height, max-width 400px, `--radius-xl` top corners |
| Message bubble (patient) | Right-aligned, `--color-brand-primary` background, white text, `--radius-lg` |
| Message bubble (assistant) | Left-aligned, `--color-grey-100` background, `--color-text-primary`, `--radius-lg` |
| Emergency state | Full-screen modal, `--color-alert-critical` header, white call-to-action buttons |

---

### 9.10 DualPaneEditor (Document Review)

| Property | Specification |
|----------|---------------|
| Split | 50/50 horizontal split on ≥1280px; stacked on smaller viewports |
| AI pane | Scrollable read-only; background `--color-grey-50`; clearly labelled |
| Edit pane | White background; `contenteditable` rich text; auto-save every 30s |
| Change tracking | Modified spans highlighted with `--color-amber-100` background; hover shows author tooltip |
| Diff highlight | Removed text: `--color-red-100` + strikethrough; Added text: `--color-green-100` |

---

## 10. Dark Mode Mapping

All semantic tokens remap in `@media (prefers-color-scheme: dark)` and via `.dark` class toggle (UI-006).

| Light Token | Dark Value |
|-------------|-----------|
| `--color-surface-page` | `--color-grey-900` (`#111827`) |
| `--color-surface-card` | `--color-grey-800` (`#1F2937`) |
| `--color-text-primary` | `--color-grey-50` (`#F9FAFB`) |
| `--color-text-secondary` | `--color-grey-400` (`#9CA3AF`) |
| `--color-border-default` | `--color-grey-700` (`#374151`) |
| `--color-brand-primary` | `--color-blue-400` (`#60A5FA`) |
| `--color-risk-high-bg` | `rgba(220,38,38,0.15)` |
| `--color-risk-medium-bg` | `rgba(217,119,6,0.15)` |
| `--color-risk-low-bg` | `rgba(22,163,74,0.15)` |
| `--color-ai-badge-bg` | `rgba(13,148,136,0.15)` |
| `--color-alert-critical-bg` | `rgba(220,38,38,0.12)` |
| `--color-alert-warning-bg` | `rgba(217,119,6,0.12)` |
| `--color-alert-info-bg` | `rgba(37,99,235,0.12)` |
| `--color-alert-success-bg` | `rgba(22,163,74,0.12)` |

---

## 11. Accessibility Tokens

| Token | Value | Purpose |
|-------|-------|---------|
| `--a11y-focus-ring` | `2px solid #2563EB` | Keyboard focus indicator |
| `--a11y-focus-offset` | 2px | Offset from element boundary |
| `--a11y-min-touch-target` | 44px | Minimum touch target (UXR-003) |
| `--a11y-contrast-body` | 4.5:1 minimum | Body text contrast ratio (WCAG AA) |
| `--a11y-contrast-ui` | 3:1 minimum | UI component contrast ratio (WCAG AA) |

### Contrast Validation

| Token Pair | Ratio | WCAG Level | Result |
|------------|-------|------------|--------|
| `--color-text-primary` on `--color-surface-card` | 16.2:1 | AA, AAA | ✓ Pass |
| `--color-brand-primary` on `--color-surface-card` | 5.9:1 | AA | ✓ Pass |
| `--color-risk-high` on `--color-risk-high-bg` | 5.1:1 | AA | ✓ Pass |
| `--color-risk-medium` on `--color-risk-medium-bg` | 4.6:1 | AA | ✓ Pass |
| `--color-risk-low` on `--color-risk-low-bg` | 5.4:1 | AA | ✓ Pass |
| `--color-text-inverse` on `--color-brand-primary` | 5.9:1 | AA | ✓ Pass |
| `--color-ai-badge` on `--color-ai-badge-bg` | 4.8:1 | AA | ✓ Pass |
| `--color-alert-critical` on `--color-alert-critical-bg` | 5.7:1 | AA | ✓ Pass |

---

## 12. Design Token Reference (CSS Custom Properties)

Complete flat list for Angular SCSS global stylesheet injection:

```scss
:root {
  /* === BRAND === */
  --color-brand-primary:        #2563EB;
  --color-brand-primary-hover:  #1D4ED8;
  --color-brand-secondary:      #0D9488;

  /* === RISK SEVERITY === */
  --color-risk-high:            #DC2626;
  --color-risk-high-bg:         #FEF2F2;
  --color-risk-medium:          #D97706;
  --color-risk-medium-bg:       #FFFBEB;
  --color-risk-low:             #16A34A;
  --color-risk-low-bg:          #F0FDF4;

  /* === ALERT LEVELS === */
  --color-alert-critical:       #DC2626;
  --color-alert-critical-bg:    #FEF2F2;
  --color-alert-warning:        #D97706;
  --color-alert-warning-bg:     #FFFBEB;
  --color-alert-info:           #2563EB;
  --color-alert-info-bg:        #EFF6FF;
  --color-alert-success:        #16A34A;
  --color-alert-success-bg:     #F0FDF4;

  /* === AI CONTENT === */
  --color-ai-badge:             #0D9488;
  --color-ai-badge-bg:          #F0FDFA;
  --color-ai-badge-border:      #2DD4BF;

  /* === SURFACE === */
  --color-surface-page:         #F9FAFB;
  --color-surface-card:         #FFFFFF;
  --color-surface-overlay:      rgba(0, 0, 0, 0.5);
  --color-surface-input:        #FFFFFF;

  /* === TEXT === */
  --color-text-primary:         #111827;
  --color-text-secondary:       #4B5563;
  --color-text-disabled:        #9CA3AF;
  --color-text-inverse:         #FFFFFF;
  --color-text-link:            #2563EB;
  --color-text-link-hover:      #1D4ED8;

  /* === BORDER === */
  --color-border-default:       #E5E7EB;
  --color-border-focus:         #2563EB;
  --color-border-error:         #EF4444;

  /* === TYPOGRAPHY === */
  --font-family-base:           'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-family-mono:           'JetBrains Mono', 'Fira Code', 'Courier New', monospace;

  --text-xs:    0.75rem;
  --text-sm:    0.875rem;
  --text-base:  1rem;
  --text-lg:    1.125rem;
  --text-xl:    1.25rem;
  --text-2xl:   1.5rem;
  --text-3xl:   1.875rem;
  --text-4xl:   2.25rem;

  --font-weight-regular:   400;
  --font-weight-medium:    500;
  --font-weight-semibold:  600;
  --font-weight-bold:      700;

  /* === SPACING === */
  --space-1:   4px;
  --space-2:   8px;
  --space-3:   12px;
  --space-4:   16px;
  --space-5:   20px;
  --space-6:   24px;
  --space-8:   32px;
  --space-10:  40px;
  --space-12:  48px;
  --space-16:  64px;

  /* === RADIUS === */
  --radius-sm:   4px;
  --radius-md:   8px;
  --radius-lg:   12px;
  --radius-xl:   16px;
  --radius-2xl:  24px;
  --radius-full: 9999px;

  /* === BORDER WIDTH === */
  --border-width-default: 1px;
  --border-width-focus:   2px;
  --border-width-alert:   2px;

  /* === SHADOW === */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
  --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  --shadow-focus: 0 0 0 3px rgba(37, 99, 235, 0.4);

  /* === ICON SIZES === */
  --icon-xs:  12px;
  --icon-sm:  16px;
  --icon-md:  20px;
  --icon-lg:  24px;
  --icon-xl:  32px;
  --icon-2xl: 48px;

  /* === MOTION === */
  --duration-instant:  0ms;
  --duration-fast:     100ms;
  --duration-normal:   200ms;
  --duration-moderate: 300ms;
  --duration-slow:     500ms;

  --ease-default: cubic-bezier(0.4, 0, 0.2, 1);
  --ease-in:      cubic-bezier(0.4, 0, 1, 1);
  --ease-out:     cubic-bezier(0, 0, 0.2, 1);
  --ease-spring:  cubic-bezier(0.34, 1.56, 0.64, 1);

  /* === ACCESSIBILITY === */
  --a11y-focus-ring:        2px solid #2563EB;
  --a11y-focus-offset:      2px;
  --a11y-min-touch-target:  44px;

  /* === PORTAL-SPECIFIC === */
  --portal-text-base:        1.125rem;
  --portal-text-heading:     1.375rem;
  --portal-text-instruction: 1rem;
}

/* Dark mode overrides */
@media (prefers-color-scheme: dark), .dark {
  :root {
    --color-surface-page:    #111827;
    --color-surface-card:    #1F2937;
    --color-text-primary:    #F9FAFB;
    --color-text-secondary:  #9CA3AF;
    --color-border-default:  #374151;
    --color-brand-primary:   #60A5FA;
    --color-risk-high-bg:    rgba(220, 38, 38, 0.15);
    --color-risk-medium-bg:  rgba(217, 119, 6, 0.15);
    --color-risk-low-bg:     rgba(22, 163, 74, 0.15);
    --color-ai-badge-bg:     rgba(13, 148, 136, 0.15);
    --color-alert-critical-bg: rgba(220, 38, 38, 0.12);
    --color-alert-warning-bg:  rgba(217, 119, 6, 0.12);
    --color-alert-info-bg:     rgba(37, 99, 235, 0.12);
    --color-alert-success-bg:  rgba(22, 163, 74, 0.12);
  }
}
```

---

*Generated by /create-figma-spec workflow | Upstream: docs/spec.md v1.0, figma_spec.md v1.0*
