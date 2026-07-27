# Start Here, Claude

You are implementing FluentForge, an adaptive English-learning system for a learner currently around A1–A2 whose long-term goal is C2.

## First-session procedure

1. Read `CLAUDE.md`.
2. Read these files in order:
   - `docs/PRODUCT_SPEC.md`
   - `docs/SKILL_MATRIX.md`
   - `docs/ADAPTIVE_ENGINE.md`
   - `docs/ARCHITECTURE.md`
   - `docs/DATABASE_SCHEMA.md`
   - `docs/ROADMAP.md`
3. Inspect the existing code and run all available verification commands.
4. Create or update `docs/CURRENT_STATUS.md` with:
   - what works
   - what is missing
   - current risks
   - the next three concrete tasks
5. Start with the earliest incomplete roadmap milestone.

## Non-negotiable rules

- Do not replace mastery with streaks, XP, or lesson counts.
- Do not assign a single CEFR level to the whole learner. Track skill dimensions separately.
- Do not claim that a fixed vocabulary count officially defines a CEFR level.
- Do not let AI-generated feedback directly update mastery without rubric evidence and confidence thresholds.
- Do not expose model keys to the browser.
- Do not store raw audio forever by default.
- Do not ship inaccessible, keyboard-inoperable, or mobile-broken interfaces.
- Do not leave placeholders in a feature marked complete.
- Every feature must have tests and a measurable learner outcome.

## Initial implementation target

Build a vertical slice that lets a learner:

1. create a local account;
2. complete a short diagnostic;
3. receive a skill profile and daily plan;
4. complete one vocabulary retrieval activity;
5. complete one reading activity;
6. submit a short written response;
7. view corrections and updated mastery evidence;
8. return the next day and receive scheduled review items.

The vertical slice must use deterministic scoring where possible. AI scoring must return structured evidence and be clearly marked as provisional.
