# Project Memory

## Product identity

- Name: FluentForge
- Purpose: adaptive English learning from A1 to C2
- Initial learner: approximately A1–A2, aiming first for B1 and eventually C2
- Tone: serious, calm, adult, practical
- Core deployment goal: self-hostable, with optional local or cloud AI

## Permanent decisions

- Track listening, speaking, interaction, pronunciation, reading, writing, vocabulary, grammar, fluency, discourse, pragmatics, mediation, and learning strategies separately.
- Use CEFR can-do outcomes and qualitative evidence; do not define a level by a fixed word count.
- Store receptive and productive knowledge separately.
- Preserve raw attempts and evidence so scoring models can evolve.
- AI evaluation is provisional, structured, confidence-scored, and regression-tested.
- Core practice and deterministic scoring must remain available when AI is disabled.
- Prioritise meaningful production and transfer over streaks or XP.
- Default raw audio retention is short and configurable.

## Current implementation state

See `docs/CURRENT_STATUS.md`. This memory file contains durable decisions only; short-lived task state belongs in the status file.

## How to update memory

Add only stable facts that future sessions genuinely need. Put multi-step procedures in `.claude/skills/`, file-scoped conventions in `.claude/rules/`, and architectural rationale in `docs/decisions/`.
