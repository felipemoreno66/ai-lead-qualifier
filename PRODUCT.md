# Product

> Note: written non-interactively from the approved `docs/PLAN.md` and the Boss's brief. Facts below come from those; items marked (assumed) were inferred and not confirmed by David.

## Platform
web (responsive). Public form is mobile-first; dashboard is desktop-first but must work on a phone (David reviews from his phone).

## Purpose
AI Lead Qualifier is an open-source, self-hostable mini CRM. Prospects apply through a per-business form; an AI agent scores the lead 0-100 against the business's own criteria, answers its questions from the business's knowledge base with citations, and drafts a personalized follow-up. A human approves, edits or rejects every draft before anything is sent. Every LLM call is recorded (tokens, latency, cost).

## Users
- **Operator** (small business owner, admissions lead, freelancer): reviews leads between other work, often on a phone. Job: see who is worth a reply first, trust or correct the AI's reasoning, send a good reply fast.
- **Prospect** (person applying on the public form): usually on a phone, low patience, unsure which program fits. Job: apply in under two minutes and feel that a person will read it.
- **Recruiter / hiring manager** (repo audience): skims screenshots and README in under two minutes. Job: judge product thinking, UI craft and AI-engineering maturity (explainability, human-in-the-loop, cost tracking).

## Jobs to be done
- Triage: "Which leads should I look at first?" (score, tier, status at a glance)
- Decide: "Is this reply good enough to send?" (reasons per criterion, the draft, approve / edit / reject)
- Recover: "Why did this lead fail and what do I do?" (error with plain cause and Retry)
- Answer: "What do our docs say about X?" (knowledge-base chat with citations and an honest "not in the docs")
- Account: "What does this cost me?" (run log, cost per lead, metrics)

## Demo tenant
Fictional **Northwind Academy**, an online programming academy: Full Stack Bootcamp, Data & AI Course, 1:1 Mentorship. All data is fictional; no real people, no real lead data.

## Tone and voice
Calm, precise, honest. The AI is a assistant that shows its work and never decides alone. Plain English, short sentences, controls named by their action ("Approve and send", not "Submit"). Errors name the problem and the recovery. No hype, no "magic" language, no promise of outcomes.

## Anti-references
Generic SaaS dashboard templates (big-number hero tiles, identical icon cards); black-box "AI" branding (sparkles, purple gradients); heavy CRMs (Salesforce-style clutter).

## Constraints
- Next.js + Tailwind + shadcn/ui + recharts must be able to build every screen; no exotic runtime effects.
- WCAG AA: text contrast at least 4.5:1, visible focus, labelled inputs, never color alone for status or tier.
- Human-in-the-loop is the hero interaction: Approve / Edit / Reject must be the most legible thing on the lead detail screen.
- English UI (workspace form supports en/es labels).
- No paid assets, no image generation; code-led design only.
- Consent and privacy notice are required on the public form and must be plainly worded.
