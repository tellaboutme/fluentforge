# Initial Prompt for Claude Code

Open this repository and act as the lead engineer, product architect, learning-system designer, and quality owner for FluentForge.

First, read `START_HERE_CLAUDE.md`, `CLAUDE.md`, `docs/PRODUCT_SPEC.md`, `docs/SKILL_MATRIX.md`, `docs/ADAPTIVE_ENGINE.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE_SCHEMA.md`, and `docs/ROADMAP.md`. Inspect the whole repository before editing anything.

Your task is to implement the product milestone by milestone, beginning with Milestone 0. Do not build disconnected mock screens. Build verified vertical slices that create real learner evidence and persist it correctly.

Requirements:

- preserve the independent skill model rather than assigning one global level;
- keep core functionality usable without a paid AI provider;
- use AI only behind typed provider interfaces and schema-validated outputs;
- never treat lesson completion, streaks, or one AI judgment as mastery;
- preserve curriculum, prompt, rubric, evaluator, and model versions;
- use deterministic scoring whenever a reliable answer key exists;
- make all user-facing flows accessible and mobile-friendly;
- add tests before declaring a feature complete;
- run the strongest available verification commands after each coherent change;
- update `docs/CURRENT_STATUS.md` continuously;
- make reasonable engineering decisions without asking me about minor details;
- ask only when a decision would fundamentally change product scope, security, cost, or data ownership.

For your first implementation pass:

1. bootstrap current compatible dependencies and commit lockfiles;
2. make `make format`, `make lint`, `make typecheck`, `make test`, and `make test-curriculum` real and passing;
3. add PostgreSQL models, Alembic, and an initial migration for users, learner profiles, curriculum versions, skill nodes, objectives, attempts, evidence events, and skill states;
4. create a curriculum loader that imports the versioned YAML safely and idempotently;
5. replace the demo profile endpoint with a database-backed local development user;
6. implement the first diagnostic session with at least selected response, short text recall, and reading comprehension items;
7. implement evidence ingestion and a transparent initial mastery update function;
8. show the resulting skill estimates and uncertainty in the web UI;
9. add unit, integration, and one Playwright vertical-flow test;
10. document everything you changed and continue to the next incomplete task only after verification passes.

Do not stop at a plan. Inspect, implement, run, fix, and verify.
