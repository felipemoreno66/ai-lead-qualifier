---
name: AI Lead Qualifier
description: "Warm Queue" - a calm, serif-voiced lead triage UI in cream-lavender, plum and terracotta.
colors:
  background: "#F5F2FA"
  card: "#FFFFFF"
  ink: "#241B2E"
  muted: "#5E546B"
  line: "#E1DAEB"
  line-soft: "#EBE6F2"
  plum: "#3A2340"
  terracotta: "#B2432A"
  terracotta-deep: "#8F3320"
  sage: "#2F6B52"
  sage-wash: "#E3F0E8"
  amber: "#8A5A00"
  amber-wash: "#FCEFD0"
  alert-red: "#A3281C"
  alert-wash: "#FBE6E1"
  focus-blue: "#1B5BD8"
  field-border: "#8F849E"
  status-info-text: "#274A78"
  status-info-wash: "#E5ECF6"
typography:
  display:
    fontFamily: "Young Serif, Georgia, serif"
    fontSize: "clamp(2rem, 1.4rem + 2.6vw, 3.25rem)"
    fontWeight: 400
    lineHeight: 1.08
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Young Serif, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
rounded:
  field: "12px"
  card: "28px"
  dialog: "24px"
  pill: "99px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  section: "48px"
components:
  button-primary:
    backgroundColor: "{colors.terracotta}"
    textColor: "{colors.card}"
    rounded: "{rounded.pill}"
    height: "52px"
    padding: "0 24px"
  button-primary-hover:
    backgroundColor: "{colors.terracotta-deep}"
  button-secondary:
    backgroundColor: "{colors.card}"
    textColor: "{colors.plum}"
    rounded: "{rounded.pill}"
    height: "52px"
    padding: "0 24px"
  button-danger:
    backgroundColor: "{colors.card}"
    textColor: "{colors.alert-red}"
    rounded: "{rounded.pill}"
    height: "52px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    height: "52px"
    padding: "12px 16px"
  panel:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.card}"
    padding: "32px"
  nav-pill-active:
    backgroundColor: "{colors.plum}"
    textColor: "{colors.card}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  badge-status-sent:
    backgroundColor: "{colors.sage-wash}"
    textColor: "{colors.sage}"
    rounded: "{rounded.pill}"
  badge-status-pending:
    backgroundColor: "{colors.amber-wash}"
    textColor: "{colors.amber}"
    rounded: "{rounded.pill}"
  badge-status-error:
    backgroundColor: "{colors.alert-wash}"
    textColor: "{colors.alert-red}"
    rounded: "{rounded.pill}"
---

# Design System: AI Lead Qualifier

Source of truth: `apps/web/app/design.css` (component classes), `apps/web/app/globals.css` (shadcn token mapping), `apps/web/app/layout.tsx` (fonts). Ported from `designs/option-c/`. Sections marked **Planned** come from that design but are not built yet.

## Overview

**Creative North Star: "The Warm Queue"**

A small team's inbox, not a CRM. The interface is a calm, spacious queue where the operator sees who to answer first, reads the AI's reasoning in plain sentences, and decides. The serif headline voice and cool lavender-cream ground keep it human; one terracotta accent marks the single action that matters on a screen. Status and tier are never color alone: each has a shape or a word.

The density is low and the touch targets are large (52px controls) because the operator reviews from a phone and the prospect applies on one. Surfaces are flat and bordered; depth is rare.

**Key Characteristics:**
- Serif display headings (Young Serif), sans UI (Figtree), tabular numerals for scores.
- Pill-shaped actions and chips, generously rounded panels (28px).
- Plum for structure and selection, terracotta for the primary action and score accent.
- Status = colored wash + text + a distinct shape marker (circle, half, square, diamond).
- Mobile: top nav collapses into a fixed bottom tab bar; the leads table becomes stacked rows.

## Colors

A cool lavender-tinted neutral set with two voices: plum (structure) and terracotta (action). Semantic sage, amber and red carry state, always paired with text.

### Primary
- **Terracotta** (#B2432A): primary button fill, score bar fill, caret color, big score numeral, hot tier text via Deep Terracotta.
- **Deep Terracotta** (#8F3320): primary hover, links, "hot" tier text, form step labels.

### Secondary
- **Plum** (#3A2340): headings, secondary button outline and text, active nav pill, selected segment/pill fill.

### Neutral
- **Lavender Cream** (#F5F2FA): page background. **White** (#FFFFFF): cards, panels, inputs.
- **Ink** (#241B2E): body text. **Muted Plum-Grey** (#5E546B): secondary text, labels (>= 4.5:1 on the background).
- **Line** (#E1DAEB) / **Soft Line** (#EBE6F2): borders, dividers, skeleton ends. **Field Border** (#8F849E): input and pill outlines (non-text contrast).

### State
- **Sage** (#2F6B52) on **Sage Wash** (#E3F0E8): approved, sent, criterion met.
- **Amber** (#8A5A00) on **Amber Wash** (#FCEFD0): pending review, warm tier, partial criterion, warning box.
- **Alert Red** (#A3281C) on **Alert Wash** (#FBE6E1): error status, unmet criterion, field errors, danger button.
- **Info Blue** (#274A78) on **Info Wash** (#E5ECF6): "qualifying" status. **Focus Blue** (#1B5BD8): focus ring only.

### Named Rules
**The One Action Rule.** Terracotta fills at most one control per view region. Everything else is plum outline or ghost.
**The Not-Color-Alone Rule.** Every status badge carries a text label and a marker shape; tiers are words (Hot, Warm, Cold); criteria carry a text label (Met, Partial, Unmet).

## Typography

**Display Font:** Young Serif (Georgia fallback), self-hosted, 400 only.
**Body Font:** Figtree (system-ui fallback), self-hosted, 400/500/600/700.
**Mono:** `ui-monospace, "SF Mono", Menlo` for inline code in error boxes.

**Character:** a warm editorial serif over a friendly geometric sans; the serif appears only on headings, lead names in the table, legends and the big score.

### Hierarchy
- **Display** (400 serif, clamp(2rem, 1.4rem + 2.6vw, 3.25rem), 1.08, -0.015em): page `h1`.
- **Headline** (400 serif, 1.5rem, 1.2): `h2` section titles; dialogs use 1.375rem, alerts 1.25rem.
- **Big score** (400 serif, 4.5rem, 1, -0.04em, terracotta): the lead score on detail.
- **Lead name** (400 serif, 1.1875rem): table row header on desktop and mobile.
- **Body** (400, 17px desktop / 16px mobile, 1.55). Story and lead text 1.1875rem, 1.6, max 62ch.
- **Label** (600, 0.875rem-1rem): field labels, table headers (0.8125rem, muted), badges (0.875rem), tabs (0.8125rem).
- **Numerals:** `.num` uses tabular figures.

### Named Rules
**The Serif Is a Voice Rule.** Serif for titles and names only; never for buttons, labels or table data.

## Layout

Single column, centered, max-width 1040px, side padding 32px (16px on mobile), bottom padding 120px to clear the tab bar. The public application form is a 640px column; the success state is 520px. Vertical rhythm uses 8/12/16/24/32/48px steps; lead groups are separated by 44px, page sections by 48px.

Breakpoint: **760px**. Below it: body 16px, top nav hides and a fixed two-column bottom tab bar appears (safe-area aware), the leads table becomes a two-column grid per row (name and status on top, program and score below; tier and country hidden), the whole row is one tap target, key-value lists stack, panels shrink to 22px/18px padding with 24px radius, score verdict stacks.

Leads are grouped by priority with a group heading and a count line; filters (segmented pills plus a status select) live in the URL.

## Elevation & Depth

Flat and bordered. Panels and fieldsets are white with a 1px Line border on the lavender page; no card shadows. The only shadow is the modal dialog (`0 24px 48px -16px rgba(36,27,46,.4)`) over a 45% plum scrim (`rgba(36,27,46,.45)`). Row hover uses a faint lavender wash (#EFEBF6).

### Named Rules
**The Flat-Until-Modal Rule.** Depth appears only for the confirmation dialog.

## Shapes

Soft and pill-like. Controls and chips: 99px. Inputs and skeletons: 12px. Dialog and warning box: 24px; alert form box 20px; error box and panels and fieldsets: 28px (24px on mobile). The brand mark is a terracotta drop (`50% 50% 50% 4px`). Status markers: circle (new, outline ring), half-filled circle (qualifying), solid circle (pending, approved), rounded square (sent, rejected as rotated diamond), hard square (error).

## Components

### Buttons
- **Shape:** pill (99px), min-height 52px, padding 0 24px, 600 weight, 1.5px plum border.
- **Primary:** terracotta fill, white text; hover deep terracotta. **Secondary (default):** white fill, plum text; hover #EEE9F5. **Danger:** red outline and text, hover red wash. **Big:** full width, 58px, 1.125rem.
- **Active:** scale .98 over .2s. **Focus:** 3px focus-blue outline, 3px offset.

### Inputs / Fields
- White, 1.5px field border (#8F849E), 12px radius, 52px min-height, 12px/16px padding; hover border turns ink; placeholder #6B6177; caret terracotta.
- **Error:** border turns alert red, with a bold red message below (`.field-error`) and a top `.form-alert` summary (red wash, 20px radius).
- Choice **pills** (radio-like): 48px pill, field border, checked = plum fill and white text; the native input is invisible but focusable with the same focus ring. **Checkbox:** 26px, terracotta accent.
- Fieldsets are white 28px-radius cards with serif legend and a "Step n" label in deep terracotta.

### Navigation
Top bar: serif brand with terracotta drop mark, plum-outlined pill links; active = plum fill, white text (`aria-current="page"`), hover lavender wash. Mobile: bottom tab bar, icon over label, active = deep terracotta text on #F8E6DD. Skip link at top, visible on focus. Icons: lucide, 20px, 1.6 stroke.

### Status badge, tier and score
- **Badge:** pill, 0.875rem/600, marker dot plus label; one color pair per status (new neutral lavender, qualifying info, pending review amber, approved and sent sage, rejected grey-lavender, error red).
- **Tier:** bold text label (Hot deep terracotta, Warm amber, Cold #35557A, none muted).
- **Score:** tabular number plus a 44x6px bar in terracotta on Line; "Not scored" when null.

### Leads table
Header row in muted 0.8125rem; rows 16px/12px padding with top hairlines; name is a serif link (underline on hover in terracotta); mobile layout described under Layout.

### Panels, key-value lists, timeline
White bordered panel (28px radius, 32px padding). Key-value grid `minmax(120px,200px) 1fr`. Timeline rows: 150px time column plus text, hairline separated. Criteria list: name, label chip (Met/Partial/Unmet) and a one-line reason.

### Feedback
- **Error box** (red wash, 28px radius, icon, plain cause, Retry), **warning box** (amber wash), **empty state** (lavender block, 24px radius, one action), **skeleton** (1.4s shimmer, disabled under reduced motion), **status line** (`.ok` sage), **pager**.
- **Confirm dialog** (Radix alert-dialog via shadcn): white, 24px radius, right-aligned actions.

### Motion
Minimal: button background .2s and press scale (ease `cubic-bezier(.2,.8,.2,1)`), pill background .15s, skeleton shimmer. All motion is disabled under `prefers-reduced-motion`.

### Planned, from designs/option-c (not implemented)
Letter-card draft review (approve / edit / reject as the hero interaction), "Why this score" criterion breakdown with evidence, knowledge-base chat with citations (`kb.html`), and metrics/run-cost view (`metrics.html`). Build them from the existing panel, pill and badge primitives; do not introduce new accents.

## Do's and Don'ts

### Do:
- **Do** keep touch targets at or above 44px (controls are 52px).
- **Do** pair every state color with text and a shape.
- **Do** keep body text at 4.5:1 or better; use Muted (#5E546B) rather than lighter greys.
- **Do** use `.num` for scores and counts.
- **Do** use the focus-blue 3px ring everywhere; never remove outlines.

### Don't:
- **Don't** add sparkles, purple gradients or "magic" AI styling (PRODUCT.md anti-reference).
- **Don't** build big-number hero tiles or identical icon-title-text card grids.
- **Don't** use gradient text, card shadows, or side-stripe accent borders.
- **Don't** use terracotta for more than one primary action per region, or for decoration.
- **Don't** set serif type on controls, labels or table data.
