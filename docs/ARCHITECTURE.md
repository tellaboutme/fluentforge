# Architecture

## Chosen baseline

- Web/PWA: Next.js App Router, TypeScript, accessible component primitives
- API: FastAPI with Pydantic and SQLAlchemy
- Database: PostgreSQL
- Queue/cache: Redis
- Object storage: S3-compatible storage such as MinIO locally
- Worker: Python async worker initially; extract into dedicated queue framework when required
- AI: provider abstraction supporting disabled/local/cloud modes
- Speech: provider abstraction; browser recording plus server processing
- Testing: Vitest, Playwright, Pytest, contract tests, curriculum validators
- Observability: structured logs, request IDs, metrics, traces later

## Why this split

Learning logic, evidence, and mastery must be authoritative on the server. The browser owns interaction and temporary recording. Expensive or slow tasks are queued. Curriculum and prompt versions are explicit dependencies of every generated/scored object.

## Service boundaries

### Web

- onboarding;
- plan and lesson player;
- labs;
- audio recording;
- progress visualization;
- offline-capable read/review queue in later milestones.

### API

- identity and learner profile;
- curriculum retrieval;
- sessions and attempts;
- evidence and mastery;
- adaptive planning;
- review scheduling;
- content metadata;
- evaluator orchestration.

### Worker

- content processing;
- AI lesson generation;
- AI scoring;
- speech-to-text and acoustic analysis;
- review-material generation;
- report generation.

## Design requirements

- API-first and versioned;
- local development through Docker Compose;
- background jobs idempotent and retry-safe;
- prompt, rubric, model, curriculum, and evaluator versions stored with outputs;
- privacy controls for learner content;
- export and delete learner data;
- no provider lock-in in domain models.

## Future options

- native mobile wrapper only after PWA validation;
- local speech recognition;
- pgvector or separate vector store for semantic retrieval;
- collaborative classroom/teacher mode;
- official exam-specific tracks as separate modules.
