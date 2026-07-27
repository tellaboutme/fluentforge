# FluentForge

A self-hostable, adaptive English-learning platform designed to take a learner from A1 to C2 through measurable mastery rather than lesson completion.

## What makes it different

FluentForge tracks each language capability independently. A learner may be B1 in reading, A2 in speaking, and A1 in pronunciation; the planner responds to that profile instead of assigning one vague level.

The system combines:

- CEFR-aligned can-do outcomes from A1 through C2
- diagnostic and periodic assessment
- adaptive daily plans
- spaced retrieval for words, phrases, grammar, and errors
- listening, reading, writing, speaking, interaction, and mediation
- pronunciation and connected-speech work
- an AI tutor that corrects selectively and explains mistakes
- evidence-based progress, confidence, and mastery estimates
- learner-created content from articles, videos, transcripts, and personal interests

## Current state

This repository is a development-ready product and architecture skeleton. It contains:

- a runnable minimal web/API scaffold
- curriculum specifications for all six CEFR levels
- database and API designs
- AI prompt contracts
- Claude Code project instructions, skills, rules, and agents
- an implementation roadmap and quality gates

## Start here

1. Paste `PROMPT_FOR_CLAUDE.md` into Claude Code, or ask Claude to open it.
2. Read `START_HERE_CLAUDE.md`.
3. Read `CLAUDE.md` and `docs/PRODUCT_SPEC.md`.
4. Copy `.env.example` to `.env`.
5. Run the bootstrap commands described in `docs/DEVELOPMENT.md`.
6. Implement Milestone 0, then Milestone 1 from `docs/ROADMAP.md`.

## Repository map

```text
apps/web                 Next.js learner application
apps/api                 FastAPI application
packages/contracts       Shared API contracts and schemas
services/worker          Async jobs: scoring, imports, review scheduling
curriculum               Versioned learning framework and CEFR content maps
prompts                  Versioned AI prompt contracts
.claude                  Claude Code rules, skills, and specialist agents
docs                     Product, pedagogy, architecture, UX, and delivery specs
infra                     Deployment and local infrastructure
tests                     Cross-service and curriculum validation tests
```

## Product principle

**Never reward passive clicking. Reward demonstrated comprehension, recall, production, interaction, and transfer.**
