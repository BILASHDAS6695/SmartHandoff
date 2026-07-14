# SmartHandoff — Component Library

> **Artifact:** component_library | **Version:** 1.0 | **Status:** Draft
> **Date:** 2026-07-14 | **Upstream:** figma_spec.md v1.0, designsystem.md v1.0, figma_structure.json v1.0
> **Workflow:** /generate-figma | **Page:** 🎨 Design System (Figma Page 2)

---

## Table of Contents

1. [Library Overview](#1-library-overview)
2. [RiskScoreChip](#2-riskscorochip)
3. [AiBadge](#3-aibadge)
4. [AlertBanner](#4-alertbanner)
5. [PrimaryButton](#5-primarybutton)
6. [NavigationItem](#6-navigationitem)
7. [BedTile](#7-bedtile)
8. [SkeletonLoader](#8-skeletonloader)
9. [ToastNotification](#9-toastnotification)
10. [ConfirmModal](#10-confirmmodal)
11. [DualPaneEditor](#11-dualpaneeditor)
12. [ChatWidget](#12-chatwidget)
13. [InputField](#13-inputfield)
14. [KpiCard](#14-kpicard)
15. [AgentStatusBadge](#15-agentstatusbadge)
16. [Component Inventory Table](#16-component-inventory-table)

---

## 1. Library Overview

All components are defined as **Figma Component Sets** with variants using Figma's `Property=Value` naming convention. Every component:

- Uses design tokens from `designsystem.md` (no hardcoded hex values in component fills)
- Is built with **Auto Layout** (vertical or horizontal)
- Supports **dark mode** via token swapping
- Has a matching **Angular standalone component** counterpart in the implementation

**Figma naming convention:** `ComponentName / Variant=Value, State=Value`
**Example:** `RiskScoreChip / Level=High, Size=Default`

---

## 2. RiskScoreChip

**Figma component:** `RiskScoreChip`
**Used on:** SCR-002, SCR-003, SCR-004, SCR-007

Displays a patient's readmission risk score with colour, icon, and text label. Colour is never the sole indicator (WCAG 1.4.1).

### Variants

| Property | Values |
|----------|--------|
| `Level` | `Low`, `Medium`, `High` |
| `Size` | `Default`, `Large` |

### Specifications

| State | Fill | Text Colour | Icon | Border Radius |
|-------|------|-------------|------|---------------|
| `Level=Low` | `--color-risk-low-bg` (#F0FDF4) | `--color-risk-low` (#16A34A) | `check-circle` (14px) | `--radius-full` |
| `Level=Medium` | `--color-risk-medium-bg` (#FFFBEB) | `--color-risk-medium` (#D97706) | `exclamation-triangle` (14px) | `--radius-full` |
| `Level=High` | `--color-risk-high-bg` (#FEF2F2) | `--color-risk-high` (#DC2626) | `exclamation-circle` (14px) | `--radius-full` |

### Dimensions (Default)

```
Height:  28px
Padding: 4px 10px
Gap:     4px (icon → text)
Font:    Inter 12px / SemiBold
```

### Dimensions (Large)

```
Height:  36px
Padding: 6px 14px
Gap:     6px
Font:    Inter 14px / Bold
```

### Content Structure

```
[icon 14px] [score "0.82"] [label "HIGH"]
```

### Angular Selector

```typescript
<sh-risk-score-chip [score]="0.82" size="default" />
// Automatically derives level from score threshold
```

---

## 3. AiBadge

**Figma component:** `AiBadge`
**Used on:** SCR-004, SCR-005, SCR-006

Persistent badge on AI-generated content. Remains visible until clinician approval is recorded (BR-011).

### Variants

| Property | Values |
|----------|--------|
| `State` | `ReviewRequired`, `Approved` |

### Specifications

| State | Background | Text Colour | Border | Icon |
|-------|------------|-------------|--------|------|
| `ReviewRequired` | `--color-ai-badge-bg` (#F0FDFA) | `--color-ai-badge` (#0D9488) | 1px `--color-ai-badge-border` (#2DD4BF) | `sparkles` |
| `Approved` | `--color-alert-success-bg` (#F0FDF4) | `--color-alert-success` (#16A34A) | 1px `--color-alert-success` | `check-circle` |

### Dimensions

```
Height:  32px
Padding: 6px 12px
Gap:     6px
Font:    Inter 11px / SemiBold
Radius:  --radius-md (8px)
```

### Content

- `ReviewRequired`: "✨ AI-Assisted — Review Required"
- `Approved`: "✓ Approved by [Clinician Name]"

---

## 4. AlertBanner

**Figma component:** `AlertBanner`
**Used on:** SCR-004, SCR-005, SCR-006, SCR-007, SCR-008

In-page banner for surfacing alerts within content areas.

### Variants

| Property | Values |
|----------|--------|
| `Severity` | `Critical`, `Warning`, `Info`, `Success` |
| `Dismissible` | `True`, `False` |

### Specifications

| Severity | Background | Left Border (4px) | Icon | Icon Colour |
|----------|------------|-------------------|------|-------------|
| `Critical` | `--color-alert-critical-bg` | `--color-alert-critical` | `exclamation-circle` | `--color-alert-critical` |
| `Warning` | `--color-alert-warning-bg` | `--color-alert-warning` | `exclamation-triangle` | `--color-alert-warning` |
| `Info` | `--color-alert-info-bg` | `--color-alert-info` | `information-circle` | `--color-alert-info` |
| `Success` | `--color-alert-success-bg` | `--color-alert-success` | `check-circle` | `--color-alert-success` |

### Dimensions

```
Min Height: 52px
Padding:    12px 16px
Gap:        12px (icon → content)
Border:     1px solid (same colour as left border at 20% opacity)
Left Border: 4px solid
Radius:     --radius-md (8px)
```

### Auto Layout

```
Direction: HORIZONTAL
Align:     TOP
Gap:       12px
Padding:   12px 16px
```

---

## 5. PrimaryButton

**Figma component:** `PrimaryButton`
**Used on:** All screens

### Variants

| Property | Values |
|----------|--------|
| `State` | `Default`, `Hover`, `Focused`, `Disabled`, `Loading` |
| `Variant` | `Primary`, `Destructive`, `Ghost`, `GhostDestructive` |
| `Size` | `Default` (40px), `Large` (48px), `Small` (32px) |
| `IconPosition` | `None`, `Left`, `Right` |

### Specifications

| Variant/State | Background | Text | Border |
|---------------|------------|------|--------|
| Primary / Default | `--color-brand-primary` (#2563EB) | `--color-text-inverse` (#FFF) | None |
| Primary / Hover | `--color-brand-primary-hover` (#1D4ED8) | `--color-text-inverse` | None |
| Primary / Focused | `--color-brand-primary` | `--color-text-inverse` | `--shadow-focus` ring |
| Primary / Disabled | `--color-grey-300` (#D1D5DB) | `--color-text-disabled` | None |
| Primary / Loading | `--color-brand-primary` (60% opacity) | Spinner | None |
| Destructive / Default | `--color-alert-critical` (#DC2626) | `--color-text-inverse` | None |
| Ghost / Default | Transparent | `--color-brand-primary` | 1.5px `--color-brand-primary` |
| GhostDestructive | Transparent | `--color-alert-critical` | 1.5px `--color-alert-critical` |

### Dimensions

```
Default:  Height 40px, Padding 10px 20px, Radius --radius-md (8px)
Large:    Height 48px, Padding 14px 24px, Radius --radius-md (8px)
Small:    Height 32px, Padding 6px 14px,  Radius --radius-md (8px)
Font:     Inter 13px / SemiBold (Default/Small), 15px / SemiBold (Large)
```

---

## 6. NavigationItem

**Figma component:** `NavigationItem`
**Used on:** All staff screens (sidebar)

### Variants

| Property | Values |
|----------|--------|
| `State` | `Default`, `Active`, `Hover`, `Disabled` |
| `HasBadge` | `True`, `False` |

### Specifications

| State | Background | Text Colour | Left Border |
|-------|------------|-------------|-------------|
| Default | Transparent | `--color-grey-700` | None |
| Hover | `--color-grey-100` | `--color-grey-700` | None |
| Active | `--color-alert-info-bg` | `--color-brand-primary` | 3px `--color-brand-primary` |
| Disabled | Transparent | `--color-text-disabled` | None |

### Dimensions

```
Height:      40px
Padding:     10px 20px
Gap:         10px (icon → label)
Icon size:   18×18px
Font:        Inter 13px / Medium (Default), SemiBold (Active)
```

---

## 7. BedTile

**Figma component:** `BedTile`
**Used on:** SCR-007

Interactive tile representing a hospital bed in the Bed Board grid.

### Variants

| Property | Values |
|----------|--------|
| `Status` | `Clean`, `Dirty`, `Occupied`, `Blocked` |
| `HasPatient` | `True`, `False` |
| `RiskLevel` | `None`, `Low`, `Medium`, `High` (when `HasPatient=True`) |

### Specifications

| Status | Background | Border Colour | ID Colour | Status Label Colour |
|--------|------------|---------------|-----------|---------------------|
| `Clean` | #F0FDF4 | #86EFAC | #15803D | #15803D |
| `Dirty` | #FFFBEB | #FCD34D | #B45309 | #B45309 |
| `Occupied` | #EFF6FF | #93C5FD | #1D4ED8 | #1D4ED8 |
| `Blocked` | #F9FAFB | #D1D5DB | #6B7280 | #6B7280 |

### Dimensions

```
Width:   120px (desktop), min 80px (tablet)
Height:  100px
Padding: 12px
Radius:  --radius-lg (12px)
Border:  1.5px solid (status colour)
```

### Content Structure (Occupied)

```
[Bed ID — Bold 13px]
[Status label — 9px UPPER]
[Patient name — 11px Medium]
[Risk chip]
[Discharge estimate — 10px]
```

---

## 8. SkeletonLoader

**Figma component:** `SkeletonLoader`
**Used on:** All screens

### Variants

| Property | Values |
|----------|--------|
| `Type` | `TextLine`, `TextBlock`, `Card`, `TableRow`, `Chart`, `Avatar` |

### Specifications

```
Background: --color-grey-200 (#E5E7EB)
Animation:  Gradient shimmer (140deg, grey-200 → grey-100 → grey-200)
            Duration: 1.5s, infinite loop
            Disabled when prefers-reduced-motion: reduce
Radius:     --radius-sm (4px) for text lines
            --radius-lg (12px) for cards
```

### Type Dimensions

| Type | Width | Height | Notes |
|------|-------|--------|-------|
| `TextLine` | 60–100% (varies) | 16px | Multiple instances stacked 8px gap |
| `TextBlock` | 100% | 80px | 4 lines approximated |
| `Card` | 100% | 200px | Matches target card |
| `TableRow` | 100% | 52px | One row with 5 column skeletons |
| `Chart` | 100% | 180px | Rounded bar shapes |
| `Avatar` | 32px | 32px | Circle (radius: 9999px) |

---

## 9. ToastNotification

**Figma component:** `ToastNotification`
**Used on:** All screens (fixed position layer)

### Variants

| Property | Values |
|----------|--------|
| `Severity` | `Critical`, `Warning`, `Info`, `Success` |
| `Dismissible` | `True` (Critical only has forced dismiss), `False` |

### Specifications

| Severity | Left Accent (4px) | Icon |
|----------|-------------------|------|
| Critical | `--color-alert-critical` | `exclamation-circle` |
| Warning | `--color-alert-warning` | `exclamation-triangle` |
| Info | `--color-alert-info` | `information-circle` |
| Success | `--color-alert-success` | `check-circle` |

### Dimensions & Position

```
Width:       320px
Min Height:  60px
Padding:     14px 16px
Position:    Fixed, top: 16px, right: 16px (z-index: 9000)
Radius:      --radius-lg (12px)
Shadow:      --shadow-xl
Background:  --color-surface-card (#FFFFFF)
Auto-dismiss: 5s (Info, Success, Warning); manual only (Critical)
Stack:       Max 3 visible, oldest dismisses on overflow
```

### ARIA

```html
role="status" aria-live="polite"    <!-- Info, Success, Warning -->
role="alert"  aria-live="assertive" <!-- Critical -->
```

---

## 10. ConfirmModal

**Figma component:** `ConfirmModal`
**Used on:** SCR-004, SCR-005, SCR-006, SCR-007, SCR-011

Required before any irreversible action (UXR-025).

### Variants

| Property | Values |
|----------|--------|
| `Variant` | `Destructive`, `Informational` |

### Specifications

```
Max Width:   480px
Padding:     32px
Radius:      --radius-xl (16px)
Shadow:      --shadow-xl
Backdrop:    --color-surface-overlay (rgba(0,0,0,0.5))
```

### Content Structure

```
[Title — text-xl / Bold]
[Body text — text-sm / Regular]
[Checkbox or confirmation input (optional)]
[Actions row]
  [Cancel — Ghost button]
  [Confirm — Primary/Destructive button]
```

### Focus Behaviour

- Focus trapped within modal while open
- First focusable element receives focus on open
- `Escape` key fires Cancel action
- Returns focus to trigger element on close

### Angular

```html
<sh-confirm-modal
  title="Approve & Sign Discharge Summary"
  body="By approving, you are digitally signing this document. This action cannot be undone."
  confirmLabel="Approve & Sign"
  variant="informational"
  (confirmed)="onApprove()"
  (cancelled)="onCancel()"
/>
```

---

## 11. DualPaneEditor

**Figma component:** `DualPaneEditor`
**Used on:** SCR-006

Split-screen document review with AI draft (read-only) and editable version side by side.

### Variants

| Property | Values |
|----------|--------|
| `State` | `DraftPending`, `Editing`, `Approved`, `Rejected` |

### Specifications

```
Layout:      50/50 horizontal split (≥1280px)
             Stacked vertical (<1280px)
Left Pane:   Background --color-grey-100; aria-label="AI draft — read only"
Right Pane:  Background --color-surface-card; aria-label="Editable document"
Divider:     1px solid --color-border-default
```

### Diff Highlighting Tokens

| Change Type | Background | Additional Style |
|-------------|------------|-----------------|
| Modified text | `--color-amber-100` (#FEF3C7) | None |
| Removed text (AI draft) | `--color-red-100` (#FEE2E2) | `text-decoration: line-through` |
| Added text | `--color-green-100` (#D1FAE5) | None |

### Header Bar (each pane)

```
[Pane title — 12px UPPER]   [Meta: "Generated 14:32" or "Last saved 14:38"]
[Separator 1px]
```

### Footer Actions

```
[← Reject & Return]  [spacer]  [Save Draft] [Approve & Sign ✓]
```

---

## 12. ChatWidget

**Figma component:** `ChatWidget`
**Used on:** SCR-010

Patient portal AI chatbot — always accessible as a fixed FAB, expands to chat panel.

### Variants

| Property | Values |
|----------|--------|
| `State` | `Closed`, `Open`, `Typing`, `Emergency` |

### Closed (FAB) Specifications

```
Width:   56px
Height:  56px
Radius:  --radius-full (9999px)
Fill:    --color-brand-primary (#2563EB)
Shadow:  0 4px 12px rgba(37,99,235,0.4)
Icon:    chat-bubble 26px, stroke white
Position: Fixed, bottom: 16px, right: 16px
```

### Open (Chat Panel) Specifications

```
Width:   100% (mobile) / 400px max (desktop)
Height:  60vh (slide up from bottom)
Radius:  --radius-xl top corners only (16px 16px 0 0)
Shadow:  --shadow-xl
Animation: slide-up 300ms --ease-spring
```

### Message Bubble — Patient

```
Align:    Flex-end (right-aligned)
Fill:     --color-brand-primary
Text:     --color-text-inverse (white)
Radius:   16px (all) except bottom-right: 4px
Max-Width: 85% of chat panel width
Padding:  12px 14px
Font:     Inter 14px / Regular
```

### Message Bubble — Assistant

```
Align:    Flex-start (left-aligned)
Fill:     --color-surface-card (#FFFFFF)
Text:     --color-text-primary
Radius:   16px (all) except bottom-left: 4px
Shadow:   --shadow-md
Max-Width: 85%
Padding:  12px 14px
Font:     Inter 14px / Regular
```

### Emergency State Specifications

```
Trigger:  Urgency signal detected in patient message
Display:  Full-screen modal overlay (100vw × 100vh)
Fill:     --color-alert-critical (#DC2626)
Content:  Emergency icon (56px) + title + hospital numbers
Buttons:  White fills (911) + rgba(255,255,255,0.2) fill (hospital)
ARIA:     role="alertdialog", aria-modal="true", aria-label="Emergency assistance"
Focus:    911 button receives focus on open; Escape does NOT dismiss
```

---

## 13. InputField

**Figma component:** `InputField`
**Used on:** SCR-001, SCR-003, SCR-011

### Variants

| Property | Values |
|----------|--------|
| `State` | `Default`, `Focused`, `Error`, `Disabled` |
| `HasIcon` | `True`, `False` |
| `HasLabel` | `True`, `False` |

### Specifications

```
Height:   44px (touch-safe — UXR-003)
Padding:  11px 14px
Radius:   --radius-md (8px)
Font:     Inter 14px / Regular
```

| State | Border | Background | Text |
|-------|--------|------------|------|
| Default | 1.5px `--color-border-default` | `--color-surface-input` | `--color-text-primary` |
| Focused | 2px `--color-border-focus` + `--shadow-focus` | `--color-surface-input` | `--color-text-primary` |
| Error | 1.5px `--color-border-error` | `--color-alert-critical-bg` | `--color-text-primary` |
| Disabled | 1px `--color-border-default` | `--color-grey-100` | `--color-text-disabled` |

---

## 14. KpiCard

**Figma component:** `KpiCard`
**Used on:** SCR-009

### Variants

| Property | Values |
|----------|--------|
| `Trend` | `PositiveDown`, `PositiveUp`, `NegativeDown`, `NegativeUp`, `Neutral` |

### Specifications

```
Padding:  20px
Radius:   --radius-lg (12px)
Shadow:   --shadow-md
Fill:     --color-surface-card
```

### Content Structure

```
[Label — 11px UPPER / Regular / --color-text-secondary]
[Value — 32px / Bold / --color-text-primary]
[Trend — 12px / Regular]
  ↓ positive: --color-alert-success
  ↑ positive: --color-alert-success
  ↓ negative: --color-risk-high
  ↑ negative: --color-risk-high
```

---

## 15. AgentStatusBadge

**Figma component:** `AgentStatusBadge`
**Used on:** SCR-002, SCR-004, SCR-008

### Variants

| Property | Values |
|----------|--------|
| `Status` | `Active`, `Warning`, `Failed`, `Pending` |

### Specifications

| Status | Background | Text Colour | Dot Colour | Label |
|--------|------------|-------------|------------|-------|
| `Active` | `--color-alert-success-bg` | `--color-alert-success` | `--color-alert-success` | "Active" |
| `Warning` | `--color-alert-warning-bg` | `--color-alert-warning` | `--color-alert-warning` | "Warning" |
| `Failed` | `--color-alert-critical-bg` | `--color-alert-critical` | `--color-alert-critical` | "Failed" |
| `Pending` | `--color-grey-100` | `--color-grey-700` | `--color-grey-700` | "Pending" |

```
Height:      28px
Padding:     4px 10px
Gap:         5px (dot → label)
Dot:         8×8px circle
Radius:      --radius-full
Font:        Inter 11px / SemiBold
```

---

## 16. Component Inventory Table

| Component | Variants | Screens Used | Angular Selector | Status |
|-----------|----------|--------------|------------------|--------|
| `RiskScoreChip` | Level×3, Size×2 | SCR-002, 003, 004, 007 | `<sh-risk-score-chip>` | ✓ Specified |
| `AiBadge` | State×2 | SCR-004, 005, 006 | `<sh-ai-badge>` | ✓ Specified |
| `AlertBanner` | Severity×4, Dismissible×2 | SCR-004, 005, 006, 007, 008 | `<sh-alert-banner>` | ✓ Specified |
| `PrimaryButton` | Variant×4, State×5, Size×3 | All | `<sh-button>` | ✓ Specified |
| `NavigationItem` | State×4, HasBadge×2 | All staff | `<sh-nav-item>` | ✓ Specified |
| `BedTile` | Status×4, HasPatient×2, RiskLevel×4 | SCR-007 | `<sh-bed-tile>` | ✓ Specified |
| `SkeletonLoader` | Type×6 | All | `<sh-skeleton>` | ✓ Specified |
| `ToastNotification` | Severity×4, Dismissible×2 | All | `<sh-toast>` | ✓ Specified |
| `ConfirmModal` | Variant×2 | SCR-004, 005, 006, 007, 011 | `<sh-confirm-modal>` | ✓ Specified |
| `DualPaneEditor` | State×4 | SCR-006 | `<sh-dual-pane-editor>` | ✓ Specified |
| `ChatWidget` | State×4 | SCR-010 | `<sh-chat-widget>` | ✓ Specified |
| `InputField` | State×4, HasIcon×2, HasLabel×2 | SCR-001, 003, 011 | `<sh-input>` | ✓ Specified |
| `KpiCard` | Trend×5 | SCR-009 | `<sh-kpi-card>` | ✓ Specified |
| `AgentStatusBadge` | Status×4 | SCR-002, 004, 008 | `<sh-agent-status>` | ✓ Specified |

**Total:** 14 components · 72 total variant combinations

---

*Generated by /generate-figma workflow | Upstream: figma_spec.md v1.0, designsystem.md v1.0*
