# FluentForge Project Instructions

## Mission

Build a serious learning system that can support progress from beginner English to C2-level independent use. The product should feel calm, precise, motivating, and useful to an adult learner—not like a children's game.

## Before changing code

- Read the nearest relevant documentation and scoped rule file.
- Search for existing types, services, and patterns before creating new ones.
- State the learner outcome the change enables.
- For changes affecting pedagogy, assessment, adaptation, or scoring, update the related document and add validation tests.

## Required workflow

1. Plan the smallest complete vertical slice.
2. Implement domain logic before UI polish.
3. Add or update tests.
4. Run formatting, linting, type checking, unit tests, and relevant end-to-end tests.
5. Inspect the UI at mobile and desktop widths for user-facing changes.
6. Update `docs/CURRENT_STATUS.md` and `docs/DECISION_LOG.md` when architecture or product behavior changes.

## Architecture boundaries

- `apps/web` renders UI and calls APIs. It must not contain secret AI credentials or authoritative mastery logic.
- `apps/api` owns authentication, profiles, learning records, assessment, planning, and public API contracts.
- `services/worker` owns asynchronous generation, speech processing, imports, and expensive evaluation.
- `curriculum` is versioned source data. Never silently mutate historical curriculum versions.
- `prompts` are versioned product logic. Every evaluator prompt must have a schema and regression fixtures.
- `packages/contracts` is the shared contract boundary.

## Coding standards

- TypeScript: strict mode, no unexplained `any`, exhaustive handling of discriminated unions.
- Python: type hints, Pydantic boundaries, small pure domain functions, explicit UTC timestamps.
- SQL: migrations only; never edit production schemas manually.
- APIs: versioned under `/api/v1`; idempotency for retryable writes.
- Errors: actionable messages, stable machine codes, no leaked secrets.
- Accessibility: semantic HTML, labels, focus states, keyboard operation, reduced-motion support.
- Internationalization: UI strings must be externalized. English learning content may remain English, with optional learner-language explanations.

## Learning-system invariants

- Skill mastery is a probability/confidence estimate supported by evidence.
- Difficulty and CEFR are related but not identical.
- Recognition and production are stored separately.
- Receptive and productive vocabulary are stored separately.
- A correct answer with heavy hints is weaker evidence than unaided recall.
- Recent repeated attempts on the same item cannot independently prove generalized mastery.
- Mastery decays in confidence when not observed, not necessarily in underlying ability.
- Corrections should prioritize errors that block meaning, are repeated, or match the current learning objective.
- Learner-facing explanations should be understandable at or just above the learner's current level.

## Verification commands

Use the repository commands once bootstrapped:

```bash
make format
make lint
make typecheck
make test
make test-curriculum
make e2e
```

Do not declare completion if a required command is failing. If infrastructure prevents a command from running, document the exact blocker and run the strongest available substitute.
